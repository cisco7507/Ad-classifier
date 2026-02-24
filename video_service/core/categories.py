import torch
import threading
from transformers import AutoProcessor, AutoModel
import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer, util
from video_service.core.utils import logger, device, TORCH_DTYPE
from video_service.core.category_mapping import (
    CATEGORY_MAPPING_STATE,
    select_mapping_input_text,
)
try:
    import plotly.graph_objects as go
except Exception as exc:
    go = None
    logger.warning("Plotly unavailable; Nebula plot disabled: %s", exc)

siglip_model = None
siglip_processor = None

SIGLIP_ID = "google/siglip-so400m-patch14-384"
try:
    logger.info(f"Initializing SigLIP on {device} with dtype {TORCH_DTYPE}")
    siglip_model = AutoModel.from_pretrained(SIGLIP_ID, torch_dtype=TORCH_DTYPE).to(device)
    siglip_processor = AutoProcessor.from_pretrained(SIGLIP_ID)
except Exception as e:
    logger.error(f"Failed to load SigLIP: {e}")

class CategoryMapper:
    def __init__(self, csv_path=None):
        self.categories = []
        self.last_error = CATEGORY_MAPPING_STATE.last_error
        self.csv_path_used = CATEGORY_MAPPING_STATE.csv_path_used
        self.embedder = None
        self.category_embeddings = None
        self.cat_to_id = {}
        self.active = False
        self.has_nebula = False
        self.vision_text_features = None
        self._reinit_lock = threading.Lock()
        self._initialize_mapper()

    def _initialize_mapper(self):
        try:
            self.cat_to_id = dict(CATEGORY_MAPPING_STATE.category_to_id)
            self.categories = list(self.cat_to_id.keys())
            self.active = bool(CATEGORY_MAPPING_STATE.enabled)
            self.last_error = CATEGORY_MAPPING_STATE.last_error
            if not self.active:
                return
            if not self.categories:
                raise RuntimeError("Category taxonomy loaded but contains no valid rows")

            logger.info(
                "Initializing SentenceTransformer all-MiniLM-L6-v2 on %s",
                device,
            )
            self.embedder = SentenceTransformer(
                "all-MiniLM-L6-v2",
                device=device,
            )
            self.category_embeddings = self.embedder.encode(
                self.categories,
                convert_to_tensor=True,
                show_progress_bar=False,
            )

            self.vision_text_features = None
            if siglip_model is not None and siglip_processor is not None and len(self.categories) > 0:
                try:
                    vision_prompts = [f"A video ad for {cat}" for cat in self.categories]
                    text_inputs = siglip_processor(
                        text=vision_prompts,
                        padding="max_length",
                        return_tensors="pt",
                    ).to(device)
                    with torch.no_grad():
                        text_features = siglip_model.get_text_features(**text_inputs)
                        self.vision_text_features = text_features / text_features.norm(p=2, dim=-1, keepdim=True)
                except Exception as siglip_exc:
                    logger.warning("SigLIP text embedding cache unavailable: %s", siglip_exc)

            if len(self.categories) >= 3:
                from sklearn.decomposition import PCA

                self.pca = PCA(n_components=3)
                self.coords_3d = self.pca.fit_transform(self.category_embeddings.cpu().numpy()) * 1000
                self.df_3d = pd.DataFrame({
                    'x': self.coords_3d[:, 0], 'y': self.coords_3d[:, 1], 'z': self.coords_3d[:, 2],
                    'Category': self.categories, 'ColorID': range(len(self.categories))
                })
                self.has_nebula = True
                self.max_range = max(self.df_3d['x'].max() - self.df_3d['x'].min(), self.df_3d['y'].max() - self.df_3d['y'].min(), self.df_3d['z'].max() - self.df_3d['z'].min())
            else:
                self.has_nebula = False

            self.last_error = None

        except Exception as e: 
            logger.exception("Mapper init failed: %s", e)
            self.last_error = str(e)
            self.active, self.has_nebula, self.vision_text_features = False, False, None

    def _attempt_reactivate(self):
        if self.active:
            return
        if not CATEGORY_MAPPING_STATE.enabled:
            return
        with self._reinit_lock:
            if self.active:
                return
            logger.warning("category mapper inactive; attempting re-initialization")
            self._initialize_mapper()

    def map_category(
        self,
        raw_category,
        job_id=None,
        suggested_categories_text="",
        predicted_brand="",
        ocr_summary="",
    ):
        if not self.active and CATEGORY_MAPPING_STATE.enabled:
            self._attempt_reactivate()
        if not self.active:
            return {
                "canonical_category": raw_category,
                "category_id": "",
                "category_match_method": "disabled",
                "category_match_score": None,
            }

        query_text = select_mapping_input_text(
            raw_category=raw_category,
            suggested_categories_text=suggested_categories_text,
            predicted_brand=predicted_brand,
            ocr_summary=ocr_summary,
        )
        query_embedding = self.embedder.encode(
            query_text,
            convert_to_tensor=True,
            show_progress_bar=False,
        )
        scores = util.cos_sim(query_embedding, self.category_embeddings)[0]
        best_match_idx = torch.argmax(scores).item()
        score = float(scores[best_match_idx].item())

        canonical = self.categories[best_match_idx]
        category_id = str(self.cat_to_id.get(canonical, ""))
        logger.info(
            "category_map job_id=%s raw=%r matched=%r id=%s score=%.6f",
            job_id or "",
            raw_category,
            canonical,
            category_id,
            score,
        )
        return {
            "canonical_category": canonical,
            "category_id": category_id,
            "category_match_method": "embeddings",
            "category_match_score": score,
        }

    def get_closest_official_category(
        self,
        raw_category,
        job_id=None,
        suggested_categories_text="",
        predicted_brand="",
        ocr_summary="",
    ):
        match = self.map_category(
            raw_category=raw_category,
            job_id=job_id,
            suggested_categories_text=suggested_categories_text,
            predicted_brand=predicted_brand,
            ocr_summary=ocr_summary,
        )
        if match["category_match_method"] == "disabled":
            logger.info(
                "category_map job_id=%s raw=%r matched=%r id=%s score=%s",
                job_id or "",
                raw_category,
                raw_category,
                "",
                "n/a",
            )
        return match["canonical_category"], match["category_id"]

    def get_diagnostics(self):
        return {
            "category_mapping_enabled": bool(self.active),
            "category_mapping_count": len(self.cat_to_id),
            "category_csv_path_used": self.csv_path_used,
            "last_error": self.last_error if not self.active else None,
        }

    def get_nebula_plot(self, highlight_category=None):
        if go is None:
            return None
        if not self.has_nebula: return go.Figure().update_layout(title="Nebula Offline")
        fig = go.Figure()
        fig.add_trace(go.Scatter3d(x=self.df_3d['x'], y=self.df_3d['y'], z=self.df_3d['z'], mode='markers', marker=dict(size=6, color=self.df_3d['ColorID'], colorscale='Turbo', opacity=0.85, line=dict(width=0.5, color='rgba(255,255,255,0.5)')), text=self.df_3d['Category'], hoverinfo='text', name='Categories'))
        scene_dict = dict(aspectmode='cube', xaxis=dict(visible=False), yaxis=dict(visible=False), zaxis=dict(visible=False))
        
        if highlight_category and highlight_category in self.categories:
            idx = self.categories.index(highlight_category)
            px, py, pz = self.df_3d.iloc[idx][['x', 'y', 'z']]
            fig.add_trace(go.Scatter3d(x=[px], y=[py], z=[pz], mode='markers', marker=dict(size=22, color='#FF0000', symbol='diamond', line=dict(color='white', width=3)), text=[f"🎯 TARGET:<br>{highlight_category}"], hoverinfo='text', name='Selected'))
            norm_x, norm_y, norm_z = px/self.max_range, py/self.max_range, pz/self.max_range
            scene_dict['camera'] = dict(center=dict(x=norm_x, y=norm_y, z=norm_z), eye=dict(x=norm_x + 0.15, y=norm_y + 0.15, z=norm_z + 0.15))
            ui_state = f"zoomed_in_{highlight_category}"
        else:
            frames = [go.Frame(layout=dict(scene=dict(camera=dict(eye=dict(x=1.8*np.cos(np.radians(t)), y=1.8*np.sin(np.radians(t)), z=0.5))))) for t in range(0, 360, 5)]
            fig.frames = frames
            fig.update_layout(updatemenus=[dict(type="buttons", showactive=False, y=0.1, x=0.5, xanchor="center", yanchor="bottom", buttons=[dict(label="🌌 Auto-Spin Nebula", method="animate", args=[None, dict(frame=dict(duration=50, redraw=True), transition=dict(duration=0), fromcurrent=True, mode="immediate")])])])
            scene_dict['camera'] = dict(center=dict(x=0, y=0, z=0), eye=dict(x=1.8, y=1.8, z=0.5))
            ui_state = "zoomed_out_global"

        return fig.update_layout(margin=dict(l=0, r=0, b=0, t=0), scene=scene_dict, showlegend=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', uirevision=ui_state)

category_mapper = CategoryMapper()
