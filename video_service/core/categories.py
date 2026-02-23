import torch
from transformers import AutoProcessor, AutoModel
import pandas as pd
from sentence_transformers import SentenceTransformer, util
import numpy as np
import plotly.graph_objects as go
from video_service.core.utils import logger, device, TORCH_DTYPE

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
    def __init__(self, csv_path="categories.csv"):
        self.categories = []
        try:
            self.df = pd.read_csv(csv_path)
            col_name = 'Freewheel Industry Category' if 'Freewheel Industry Category' in self.df.columns else self.df.columns[1]
            id_name = 'ID' if 'ID' in self.df.columns else self.df.columns[0]
            self.cat_to_id = dict(zip(self.df[col_name].astype(str), self.df[id_name].astype(str)))
            self.categories = list(self.cat_to_id.keys())
            
            logger.info(f"Initializing SentenceTransformer on {device} with dtype {TORCH_DTYPE}")
            self.embedder = SentenceTransformer('all-MiniLM-L6-v2', device=device, model_kwargs={"torch_dtype": TORCH_DTYPE})
            self.category_embeddings = self.embedder.encode(self.categories, convert_to_tensor=True)
            self.active = True
            
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
                
            if siglip_model is not None and len(self.categories) > 0:
                vision_prompts = [f"A video ad for {cat}" for cat in self.categories]
                text_inputs = siglip_processor(text=vision_prompts, padding="max_length", return_tensors="pt").to(device)
                with torch.no_grad():
                    text_features = siglip_model.get_text_features(**text_inputs)
                    self.vision_text_features = text_features / text_features.norm(p=2, dim=-1, keepdim=True)
            else:
                self.vision_text_features = None

        except Exception as e: 
            logger.error(f"Mapper init failed: {e}")
            self.active, self.has_nebula, self.vision_text_features = False, False, None

    def get_closest_official_category(self, raw_category):
        if not self.active or not raw_category or raw_category.lower() in ["unknown", "none", "n/a", ""]: return raw_category, ""
        best_match_idx = torch.argmax(util.cos_sim(self.embedder.encode(raw_category, convert_to_tensor=True), self.category_embeddings)[0]).item()
        return self.categories[best_match_idx], self.cat_to_id.get(self.categories[best_match_idx], "")

    def get_nebula_plot(self, highlight_category=None):
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
