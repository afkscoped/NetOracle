import json
import logging
from typing import Any
import requests
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import shap

from app.database import db
from app.settings import get_settings
from app.services.graph import groq_model_candidates

logger = logging.getLogger(__name__)

class XAIService:
    def _compute_shap(self, node_id: str = None) -> dict[str, float]:
        data = db.fetch_all("SELECT * FROM telemetry ORDER BY timestamp DESC LIMIT 500")
        if not data:
            return {}
            
        df = pd.DataFrame(data)
        if 'metrics_json' in df.columns:
            metrics_df = pd.json_normalize(df['metrics_json'].apply(lambda x: json.loads(x) if isinstance(x, str) else x))
        else:
            return {}
            
        features = ['cpu', 'memory', 'latency_ms', 'packet_loss', 'throughput_mbps', 'prb_utilization']
        available_features = [f for f in features if f in metrics_df.columns]
        
        if not available_features:
            return {}
            
        X = metrics_df[available_features].fillna(0)
        y = df['fault_label'].fillna(0)
        
        if len(y.unique()) < 2:
            return {} # Need both normal and fault cases to explain
            
        model = RandomForestClassifier(n_estimators=20, max_depth=5, random_state=42)
        model.fit(X, y)
        
        explainer = shap.TreeExplainer(model)
        
        target_row = X.iloc[0:1] # Default to latest
        if node_id:
            node_idx = df[df['node_id'] == node_id].index
            if len(node_idx) > 0:
                target_row = X.iloc[node_idx[0]:node_idx[0]+1]
                
        shap_values = explainer.shap_values(target_row)
        
        if isinstance(shap_values, list):
            sv = shap_values[1][0] if len(shap_values) > 1 else shap_values[0][0]
        else:
            sv = shap_values[0]
            if len(sv.shape) > 1:
                sv = sv[0]
            
        feature_names = X.columns.tolist()
        # Convert sv to list of floats if it's a numpy array to ensure JSON serialization
        import numpy as np
        if isinstance(sv, np.ndarray):
            sv = sv.tolist()
            
        return {feat: round(float(val), 4) for feat, val in zip(feature_names, sv)}

    def generate_explanation(self, tab_name: str, node_id: str = None) -> dict[str, Any]:
        settings = get_settings()
        if not settings.groq_api_key:
            return {"explanation": "Groq API key not configured for XAI."}
            
        try:
            shap_vals = self._compute_shap(node_id)
        except Exception as e:
            logger.error(f"SHAP computation failed: {e}")
            shap_vals = {}
            
        system_prompt = (
            "You are an intuitive, expert Explainable AI (XAI) assistant for a gamified 5G NOC dashboard. "
            "Your job is to explain dynamically what the user is seeing in the current tab, and why the network "
            "is behaving the way it is based on the data provided. Keep explanations concise, impactful, and easy to understand. "
            "Address the user directly. Explain the SHAP values as 'key drivers' of the current situation. "
            "Also provide creative, innovative suggestions on how to avoid potential faults — consider techniques like "
            "predictive scaling, traffic shaping, dynamic resource reallocation, edge computing offload, and AI-driven SLA management. "
            "Return ONLY valid JSON matching this schema: "
            '{"explanation": "<your explanation here>", "suggestions": ["<suggestion 1>", "<suggestion 2>", "<suggestion 3>"], '
            '"risk_level": "low|medium|high", "key_drivers": ["<driver 1>", "<driver 2>"]}'
        )
        
        user_prompt = f"The user is currently looking at the '{tab_name}' tab.\n"
        if shap_vals:
            user_prompt += f"SHAP Feature Importance (how much each metric contributed to the current fault risk):\n{json.dumps(shap_vals, indent=2)}\n"
            user_prompt += "Explain these SHAP values simply, telling the user which metrics are driving the fault risk right now.\n"
        else:
            user_prompt += "No SHAP values available (either no faults recently or insufficient data).\nExplain the purpose of this tab briefly.\n"

        # Try each model candidate until one succeeds
        for model in groq_model_candidates():
            try:
                response = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.3,
                        "response_format": {"type": "json_object"}
                    },
                    timeout=20,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                result = json.loads(content)
                result["_model_used"] = model
                result["shap_values"] = shap_vals
                return result
            except Exception as e:
                logger.warning(f"Groq XAI failed for model {model}: {e}")
                continue

        return {
            "explanation": "XAI service temporarily unavailable. SHAP values computed locally.",
            "shap_values": shap_vals,
            "suggestions": ["Monitor trending metrics", "Review causal graph for root causes", "Consider proactive scaling"],
            "risk_level": "medium" if shap_vals else "low",
            "key_drivers": sorted(shap_vals.keys(), key=lambda k: abs(shap_vals.get(k, 0)), reverse=True)[:3] if shap_vals else [],
        }

xai_service = XAIService()
