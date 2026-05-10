from datetime import datetime, timezone
from typing import Any

from app.database import db
from app.services.graph import graph_service
from app.services.proactive_engine import proactive_engine

DEVICE_GLOSSARY = {
    "AMF": "Access and Mobility Management Function. It is like the front desk of the 5G core: it registers devices, manages mobility, and keeps track of where users are connected.",
    "SMF": "Session Management Function. It creates and manages data sessions, deciding how user traffic should travel through the 5G core.",
    "UPF": "User Plane Function. It is the data gateway that carries real user traffic between phones, applications, and the internet.",
    "PCF": "Policy Control Function. It stores policy rules such as QoS, charging, throttling, and slice behavior.",
    "NRF": "Network Repository Function. It is the service directory where 5G core functions discover each other.",
    "gNB": "5G base station. It connects phones and IoT devices over radio and forwards their traffic into the core network.",
    "VNF": "Virtual Network Function. A telecom function running as software, so it can be scaled, restarted, or moved.",
    "Slice": "A logical network reserved for a use case, such as high-throughput broadband, IoT, or ultra-low-latency services.",
    "PRB": "Physical Resource Block. A small unit of radio capacity; high PRB utilization means the radio layer is getting crowded.",
    "SLA": "Service Level Agreement. The promised performance limit, such as maximum latency or packet loss.",
    "DAG": "Directed Acyclic Graph. A graph with arrows and no loops, used here to show likely cause-effect relationships.",
    "CTGNN": "Causal Temporal Graph Neural Network. A model that learns how network metrics evolve over time and across causal graph edges.",
    "CMDP": "Constrained Markov Decision Process. A reinforcement-learning policy that is allowed to optimize only when safety limits are respected.",
    "RAG": "Retrieval-Augmented Generation. The LLM is grounded with past incidents and graph context instead of guessing from memory alone.",
    "SHAP": "A feature-attribution method that estimates how much each metric pushed a prediction up or down.",
}

METRIC_GLOSSARY = {
    "cpu": "Compute load on a network function. Sustained high CPU creates queues and delays.",
    "memory": "Memory pressure on a service. Rising memory can indicate leaks or overloaded VNFs.",
    "latency_ms": "Delay in milliseconds. Higher latency means users wait longer for network responses.",
    "packet_loss": "Fraction of packets that disappear or are dropped. Loss causes retransmissions, slow apps, and voice/video glitches.",
    "throughput_mbps": "Useful traffic rate in megabits per second. Drops can reveal congestion, shaping, or link trouble.",
    "prb_utilization": "Radio resource usage. High values mean the radio layer has little spare capacity.",
}

TAB_MANIFESTS = {
    "dashboard": {
        "purpose": "This is the live NOC cockpit. It shows whether the system is healthy now and which component is most likely to fail soon.",
        "features": [
            "Fault Probability estimates future risk instead of waiting for hard threshold alarms.",
            "Proactive Forecast shows T+5, T+10, and T+20 minute risk so operators can act before SLA damage.",
            "Realtime Core panel analyses the active telemetry source and simulates best fixes.",
            "3D Twin opens a holographic network view that maps risks to infrastructure nodes.",
        ],
        "buttons": {
            "Tick": "Generates one telemetry tick and immediately refreshes charts and alerts.",
            "Refresh": "Reloads telemetry, topology, causal graph, audit trail, forecasts, metrics, and explanations.",
            "3D Twin": "Shows the network as an interactive digital twin.",
            "Explain Tab": "Opens the XAI panel for the current tab.",
        },
        "operator_questions": ["What is likely to fail next?", "How much time do we have?", "Which metric is driving the risk?", "What action is safe?"],
    },
    "intelligence": {
        "purpose": "This tab proves that NetOracle is not only plotting metrics; it is learning likely cause-effect structure.",
        "features": [
            "NOTEARS discovers an acyclic causal graph from recent telemetry.",
            "Federated voting merges slice-level causal edges into a global view.",
            "Benchmarks compare NetOracle against simpler baselines using AUC, false-positive rate, and lead time.",
            "DAG history helps reviewers see whether causal structure is stable or drifting.",
        ],
        "buttons": {
            "Refresh DAG": "Recomputes and redraws causal edges using the latest telemetry.",
            "Run Benchmark": "Runs live benchmark scenarios and renders model-vs-baseline bars.",
        },
        "operator_questions": ["Which metric tends to move first?", "Is the model better than thresholds?", "Are causal edges stable across slices?"],
    },
    "topology": {
        "purpose": "This tab connects predictions to real infrastructure so the team can localise blast radius.",
        "features": [
            "The property graph stores nodes, services, slices, and relations in a Neo4j-compatible shape.",
            "Node inspector explains selected infrastructure and shows recent metric sparkline history.",
            "NL-to-Cypher lets operators ask graph questions without writing query syntax.",
            "Path highlighting reveals which dependencies might carry a fault cascade.",
        ],
        "buttons": {
            "Refresh": "Reloads topology nodes, edges, risk colors, and the node inspector data.",
            "Ask": "Converts a natural-language topology question into graph lookup logic.",
            "Explain node": "Explains one selected network element, its role, and its risk context.",
        },
        "operator_questions": ["Where is the fault located?", "What depends on this node?", "Which neighbors are affected?", "What does this device type do?"],
    },
    "diagnosis": {
        "purpose": "This tab demonstrates the closed loop: inject/observe fault, localise it, diagnose root cause, and choose a safe response.",
        "features": [
            "Fault injection creates controlled test events for demos and validation.",
            "GraphRAG grounds the LLM using topology plus past incident memory.",
            "MoE specialists debate root cause from radio, core, transport, and security viewpoints.",
            "Risk-gated remediation blocks unsafe automation and escalates when confidence is insufficient.",
        ],
        "buttons": {
            "Run Closed-Loop Demo": "Runs telemetry, prediction, graph localisation, diagnosis, remediation, audit, and UI refresh together.",
            "Inject Fault Only": "Adds fault telemetry without forcing the full diagnosis sequence.",
            "Ask": "Asks an investigation question while analysing an incident.",
        },
        "operator_questions": ["What caused the fault?", "What evidence supports it?", "Which specialist agreed?", "Can we safely remediate?"],
    },
    "wireless": {
        "purpose": "This tab shows optimization and safety control for radio/resource decisions.",
        "features": [
            "Hopfield allocation searches for low-energy channel assignments under interference constraints.",
            "Jain fairness shows whether resources are distributed evenly.",
            "CMDP policy chooses remediation only when safety budgets allow it.",
            "Stress tests compare light and heavy allocation pressure.",
        ],
        "buttons": {
            "Run Allocator": "Runs Hopfield sub-channel assignment and visualizes selected channels.",
            "Show Policy State": "Displays CMDP constraints and policy health.",
            "Run Allocation Stress Test": "Compares allocation quality under different loads.",
            "Export Audit Report": "Saves audit evidence locally.",
            "Export Benchmark Report": "Saves benchmark evidence locally.",
        },
        "operator_questions": ["Are resources allocated fairly?", "Did the optimizer converge?", "Which actions are blocked by safety constraints?"],
    },
    "audit": {
        "purpose": "This tab is the evidence ledger. It makes every prediction, diagnosis, export, and safety decision reviewable.",
        "features": [
            "Each event stores timestamp, event type, and structured payload.",
            "Audit completeness proves that the closed loop is traceable.",
            "Event explanations translate raw JSON into supervisor-friendly narratives.",
        ],
        "buttons": {
            "All Events": "Filters the event ledger by type.",
            "Explain": "Explains the selected audit event and the fields that matter.",
        },
        "operator_questions": ["Can we prove what the model did?", "Was an unsafe action blocked?", "Which evidence led to the final decision?"],
    },
    "datasources": {
        "purpose": "This tab makes NetOracle adaptive. It can run on built-in priors, generated realistic data, uploaded telemetry, uploaded topology, or Open5GS-shaped streams.",
        "features": [
            "Realistic generation uses public-dataset-inspired ranges, diurnal load, correlated metrics, and fault cascades.",
            "Uploads must match the canonical telemetry/topology schemas.",
            "Export-retrain converts live telemetry into a training file and starts the local training pipeline.",
            "Quality checks measure completeness, freshness, schema validity, and drift from the expected profile.",
        ],
        "buttons": {
            "Open5GS Real-Time Core": "Switches source mode to Open5GS adapter/fallback.",
            "Fallback Simulation": "Switches source mode to simulation.",
            "CSV Stream": "Switches source mode to CSV streaming.",
            "Prometheus": "Switches source mode to Prometheus adapter.",
            "Analyse Open5GS Now": "Runs one Open5GS-shaped analysis cycle.",
            "Generate & Load": "Creates realistic telemetry and ingests it into the active database.",
            "Train Model on This Data": "Exports telemetry and starts retraining.",
            "Upload Telemetry": "Loads user telemetry rows into the canonical store.",
            "Upload Topology": "Loads user topology nodes and edges.",
            "Analyse Uploaded Data": "Runs prediction, localisation, diagnosis, and remediation on uploaded data.",
        },
        "operator_questions": ["Is this data valid?", "Does it match training assumptions?", "Can the whole platform adapt to a new network?", "Can we retrain on the new data?"],
    },
    "executive": {
        "purpose": "This tab answers the supervisor's first question: what makes NetOracle different from existing tools?",
        "features": [
            "It compares reactive threshold monitoring against predictive causal intelligence.",
            "It shows benchmark-backed gains, explainability, safe automation, and auditability.",
            "It summarizes the Full Trilogy: Preventive Autopilot, Adaptive Data Twin, and Executive Proof Mode.",
        ],
        "buttons": {
            "Refresh Proof": "Rebuilds the evidence summary from live metrics, benchmarks, alerts, and audit data.",
            "Run Benchmark": "Refreshes benchmark evidence used by proof mode.",
        },
        "operator_questions": ["Why is this better?", "Can it prevent faults before impact?", "Can it adapt to new data?", "Can it prove decisions?"],
    },
}

THEORY_BY_TAB = {
    "dashboard": {
        "title": "Predictive risk scoring",
        "equation": "P_fault = σ(w₁·latency + w₂·loss + w₃·PRB + w₄·CPU + graph_prior)",
        "meaning": "The dashboard ranks nodes by future SLA breach probability, not just current threshold violations.",
    },
    "intelligence": {
        "title": "NOTEARS causal discovery",
        "equation": "min_W L(X,W)+λ||W||₁ subject to h(W)=tr(e^{W⊙W})-d=0",
        "meaning": "Edges represent candidate cause-effect relations that remain acyclic and stable across slices.",
    },
    "topology": {
        "title": "Graph risk propagation",
        "equation": "R(v)=σ(αP(v)+βΣᵤR(u)w_uv+γC(v))",
        "meaning": "A node is risky when its local metrics are bad and its upstream/downstream dependencies amplify blast radius.",
    },
    "diagnosis": {
        "title": "Graph-grounded multi-agent diagnosis",
        "equation": "RootCause = argmax_c Σᵢ voteᵢ(c)·confidenceᵢ·graph_support(c)",
        "meaning": "Specialist agents vote, but topology and telemetry evidence constrain the final root cause.",
    },
    "wireless": {
        "title": "CMDP + Hopfield resource control",
        "equation": "maximize E[Σγᵗr_t] subject to E[Σγᵗc_t]≤Cmax; E_H=-1/2ΣᵢΣⱼwᵢⱼsᵢsⱼ+Σᵢθᵢsᵢ",
        "meaning": "The allocator searches for low-energy channel assignments while the CMDP blocks unsafe actions.",
    },
    "audit": {
        "title": "Causal confidence ledger",
        "equation": "Trust = calibration × data_quality × causal_agreement × model_confidence",
        "meaning": "Every event is explainable as a chain of evidence, decision, and safety gate.",
    },
    "datasources": {
        "title": "Data reliability and drift",
        "equation": "Quality = completeness × freshness × schema_validity × distribution_similarity",
        "meaning": "The system checks whether incoming data is fresh, complete, and compatible with the training schema.",
    },
    "executive": {
        "title": "Operational value proof",
        "equation": "Value = lead_time × localisation × safe_action × auditability × adaptability",
        "meaning": "The differentiator is not one model; it is the closed-loop chain from forecast to safe, explainable prevention.",
    },
}


class ExplainabilityService:
    def _feature_evidence(self, forecast: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not forecast:
            return []
        labels = {
            "latency_ms": "Latency is rising toward the slice SLA limit.",
            "packet_loss": "Packet loss is increasing, often preceding retransmissions and latency spikes.",
            "prb_utilization": "Radio resource pressure is high and can trigger congestion.",
            "throughput_mbps": "Throughput is dropping relative to expected demand.",
            "cpu": "Compute load is elevated on a network function.",
            "memory": "Memory pressure suggests VNF degradation or leak risk.",
        }
        slopes = forecast.get("metric_slopes", {})
        evidence = []
        for idx, feature in enumerate(forecast.get("top_drivers", []), start=1):
            evidence.append({
                "rank": idx,
                "feature": feature,
                "interpretation": labels.get(feature, "This metric is contributing materially to predicted risk."),
                "layman_definition": METRIC_GLOSSARY.get(feature, "A network measurement used by the prediction model."),
                "trend_per_tick": slopes.get(feature),
            })
        return evidence

    def _glossary_for_tab(self, tab: str, forecast: dict[str, Any] | None) -> dict[str, str]:
        keys = {
            "dashboard": ["SLA", "CTGNN", "SHAP", "UPF", "gNB"],
            "intelligence": ["DAG", "CTGNN", "SLA", "PRB"],
            "topology": ["AMF", "SMF", "UPF", "PCF", "NRF", "gNB", "Slice", "VNF"],
            "diagnosis": ["RAG", "DAG", "CMDP", "AMF", "SMF", "UPF", "gNB"],
            "wireless": ["PRB", "CMDP", "SLA", "gNB"],
            "audit": ["SLA", "DAG", "CMDP", "RAG"],
            "datasources": ["Slice", "VNF", "SLA", "PRB", "CTGNN"],
            "executive": ["CTGNN", "DAG", "RAG", "CMDP", "SHAP", "SLA"],
        }.get(tab, ["SLA", "CTGNN", "DAG"])
        if forecast:
            node = str(forecast.get("node_id", "")).lower()
            if "upf" in node:
                keys.append("UPF")
            if "gnb" in node:
                keys.append("gNB")
            if "amf" in node:
                keys.append("AMF")
            if "smf" in node:
                keys.append("SMF")
        return {key: DEVICE_GLOSSARY[key] for key in dict.fromkeys(keys) if key in DEVICE_GLOSSARY}

    def _component_explanations(self, tab: str) -> list[str]:
        manifest = TAB_MANIFESTS.get(tab, TAB_MANIFESTS["dashboard"])
        return manifest.get("features", [])

    def _trust_score(self, forecast: dict[str, Any] | None) -> dict[str, Any]:
        if not forecast:
            return {"score": 0.0, "components": {}}
        model_confidence = float(forecast.get("confidence", 0.6))
        data_quality = 0.92 if forecast.get("top_drivers") else 0.7
        causal_agreement = 0.78 if forecast.get("top_drivers") else 0.55
        calibration = 0.82 if forecast.get("model") != "multi_horizon_heuristic" else 0.68
        score = round(model_confidence * data_quality * causal_agreement * calibration, 3)
        return {
            "score": score,
            "components": {
                "model_confidence": round(model_confidence, 3),
                "data_quality": data_quality,
                "causal_agreement": causal_agreement,
                "calibration": calibration,
            },
        }

    def explain_tab(self, tab_name: str, node_id: str | None = None) -> dict[str, Any]:
        tab = tab_name.lower().replace("tab-", "")
        theory = THEORY_BY_TAB.get(tab, THEORY_BY_TAB["dashboard"])
        latest = proactive_engine.latest()
        forecast = latest.get("top_forecast")
        if node_id and latest.get("forecasts"):
            forecast = next((item for item in latest["forecasts"] if item.get("node_id") == node_id), forecast)
        narrative = latest.get("narrative") or "NetOracle is waiting for enough telemetry to generate a proactive explanation."
        if tab == "intelligence":
            narrative = "The causal graph shows which metrics tend to move before others. Strong edges are used as causal priors for proactive prediction."
        elif tab == "topology" and forecast:
            path = graph_service.localise({"slice_id": forecast["slice_id"], "node_id": forecast["node_id"], "alert_id": "explain"}).get("affected_path", [])
            path_ids = [
                item.get("node_id", str(item)) if isinstance(item, dict) else str(item)
                for item in path
            ]
            narrative = f"Topology analysis localizes risk around {forecast['node_id']}. Affected path: {' -> '.join(path_ids) if path_ids else forecast['node_id']}."
        elif tab == "diagnosis" and forecast:
            narrative = f"Diagnosis should focus on {forecast['fault_type']} at {forecast['node_id']} because {', '.join(forecast.get('top_drivers', []))} are leading risk drivers."
        elif tab == "wireless" and forecast:
            narrative = f"The policy should prefer {forecast['recommended_action'].replace('_', ' ')} if CMDP safety constraints remain satisfied."
        elif tab == "audit":
            narrative = "The audit trail records each forecast, diagnosis, remediation decision, and export as a causal confidence ledger."
        elif tab == "datasources":
            narrative = "Data source health is judged by schema validity, freshness, completeness, and drift from training distributions."
        elif tab == "executive":
            narrative = "Executive Proof Mode connects measurable model performance, proactive lead time, safe automation, data adaptivity, and audit evidence into one defensible story."
        manifest = TAB_MANIFESTS.get(tab, TAB_MANIFESTS["dashboard"])
        result = {
            "tab": tab,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "headline": self._headline(tab, forecast),
            "narrative": narrative,
            "layman_summary": manifest["purpose"],
            "technical_details": self._component_explanations(tab),
            "button_guide": manifest.get("buttons", {}),
            "operator_questions": manifest.get("operator_questions", []),
            "device_glossary": self._glossary_for_tab(tab, forecast),
            "metric_glossary": METRIC_GLOSSARY,
            "evidence": self._feature_evidence(forecast),
            "theory": theory,
            "trust": self._trust_score(forecast),
            "recommended_next_step": self._next_step(forecast),
            "forecast": forecast,
        }
        db.audit("explain_tab", {"tab": tab, "node_id": node_id, "headline": result["headline"]})
        return result

    def explain_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_type = payload.get("event_type", "event")
        data = payload.get("payload", payload)
        return {
            "headline": f"Explanation for {event_type}",
            "narrative": f"NetOracle recorded {event_type}. The important decision fields are action, confidence, risk, node, and safety status.",
            "key_fields": {key: data.get(key) for key in ["node_id", "slice_id", "fault_type", "action", "confidence", "risk", "status"] if key in data},
            "theory": THEORY_BY_TAB["audit"],
            "device_glossary": self._glossary_for_tab("audit", None),
        }

    def explain_node(self, node_id: str) -> dict[str, Any]:
        latest = proactive_engine.latest()
        forecast = next((item for item in latest.get("forecasts", []) if item.get("node_id") == node_id), None)
        topology = graph_service.get_node_neighbourhood(node_id, depth=2)
        return {
            "node_id": node_id,
            "headline": self._headline("topology", forecast),
            "forecast": forecast,
            "neighbourhood": topology,
            "evidence": self._feature_evidence(forecast),
            "theory": THEORY_BY_TAB["topology"],
            "trust": self._trust_score(forecast),
            "device_glossary": self._glossary_for_tab("topology", forecast),
            "metric_glossary": METRIC_GLOSSARY,
            "layman_summary": f"{node_id} is being inspected as a network element. Its neighbourhood shows dependencies that may amplify or absorb faults.",
        }

    def latest_prediction_explanation(self) -> dict[str, Any]:
        return self.explain_tab("dashboard")

    def _headline(self, tab: str, forecast: dict[str, Any] | None) -> str:
        if not forecast:
            return "System collecting telemetry baseline"
        breach = forecast.get("predicted_breach_time_min")
        if breach is not None and breach <= 10:
            return f"Prevent {forecast['fault_type'].replace('_', ' ')} on {forecast['node_id']} within {breach} min"
        return f"Watch {forecast['node_id']}: future risk {round(forecast.get('risk_t_plus_10', 0)*100)}%"

    def _next_step(self, forecast: dict[str, Any] | None) -> str:
        if not forecast:
            return "Allow telemetry to warm up, then run a demo or ingest CSV/Open5GS data."
        if forecast.get("risk_t_plus_10", 0) >= 0.65:
            return f"Review and simulate {forecast['recommended_action'].replace('_', ' ')} before SLA breach."
        return "Continue monitoring; no immediate preventive action is required."


explainability_service = ExplainabilityService()
