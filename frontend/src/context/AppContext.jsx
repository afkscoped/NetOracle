import React, { createContext, useState, useEffect, useRef } from 'react';
import { api } from '../utils/api';

export const AppContext = createContext();

export function AppProvider({ children }) {
  const [telemetry, setTelemetry] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [metrics, setMetrics] = useState({
    fault_probability: 0.0,
    prediction_auc: 0.95,
    model_type: 'CTGNN (Causal-Temporal GNN)',
    confidence: 0.98,
  });
  const [dataMode, setDataMode] = useState('simulation');
  const [open5gsHealth, setOpen5gsHealth] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [latestAlert, setLatestAlert] = useState(null);
  const wsRef = useRef(null);

  // Fetch initial telemetry
  const refreshTelemetry = async () => {
    try {
      // api.get unwraps {ok,data} -> returns array directly
      const data = await api.get('/api/telemetry/recent');
      if (Array.isArray(data)) {
        // Normalize nested metrics fields to top level
        const normalized = data.map((f) => ({
          ...f,
          cpu: f.cpu ?? f.metrics?.cpu ?? 0,
          memory: f.memory ?? f.metrics?.memory ?? 0,
          latency_ms: f.latency_ms ?? f.metrics?.latency_ms ?? 0,
          packet_loss: f.packet_loss ?? f.metrics?.packet_loss ?? 0,
          throughput_mbps: f.throughput_mbps ?? f.metrics?.throughput_mbps ?? 0,
          prb_utilization: f.prb_utilization ?? f.metrics?.prb_utilization ?? 0,
        }));
        setTelemetry(normalized);
      }
    } catch (err) {
      console.error('Failed to fetch recent telemetry:', err);
    }
  };

  // Fetch initial metrics
  const refreshMetrics = async () => {
    try {
      const data = await api.get('/api/metrics');
      if (data) {
        setMetrics(prev => ({ ...prev, ...data }));
      }
    } catch (err) {
      // Endpoint might not return full metrics, fallback gracefully
      console.warn('Could not fetch custom metrics, using default.', err);
    }
  };

  // Fetch initial alerts
  const refreshAlerts = async () => {
    try {
      const data = await api.get('/api/alerts');
      if (Array.isArray(data)) {
        setAlerts(data);
      }
    } catch (err) {
      console.error('Failed to fetch alerts:', err);
    }
  };

  // Refresh data mode
  const refreshDataMode = async () => {
    try {
      // Unwrapped response has shape {mode, prometheus_reachable, ...}
      const modeData = await api.get('/api/data/mode');
      if (modeData && modeData.mode) {
        setDataMode(modeData.mode);
      }
    } catch (err) {
      console.error('Failed to fetch data mode:', err);
    }
  };

  // Connect WebSocket
  useEffect(() => {
    let reconnectTimer;
    
    function connectWS() {
      const wsUrl = `ws://${window.location.hostname}:8000/ws/telemetry`;
      console.log('Connecting to WebSocket:', wsUrl);
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        console.log('WebSocket connected');
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'tick') {
            // Normalize frames: backend returns frame.metrics.cpu but charts expect frame.cpu
            if (data.frames && data.frames.length > 0) {
              const normalized = data.frames.map((f) => ({
                ...f,
                cpu: f.cpu ?? f.metrics?.cpu ?? 0,
                memory: f.memory ?? f.metrics?.memory ?? 0,
                latency_ms: f.latency_ms ?? f.metrics?.latency_ms ?? 0,
                packet_loss: f.packet_loss ?? f.metrics?.packet_loss ?? 0,
                throughput_mbps: f.throughput_mbps ?? f.metrics?.throughput_mbps ?? 0,
                prb_utilization: f.prb_utilization ?? f.metrics?.prb_utilization ?? 0,
              }));
              setTelemetry((prev) => {
                const combined = [...prev, ...normalized];
                return combined.slice(-50);
              });
            }

            if (data.alert) {
              setLatestAlert(data.alert);
              if (data.alert.fault_probability > 0.4) {
                setAlerts((prev) => [
                  { timestamp: new Date().toISOString(), ...data.alert },
                  ...prev,
                ].slice(0, 100));
              }
            }

            if (data.metrics) {
              setMetrics((prev) => ({ ...prev, ...data.metrics }));
            }
          }
        } catch (err) {
          console.error('Error parsing WebSocket message:', err);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        console.log('WebSocket disconnected. Reconnecting...');
        reconnectTimer = setTimeout(connectWS, 3000);
      };

      ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        ws.close();
      };
    }

    connectWS();
    refreshTelemetry();
    refreshAlerts();
    refreshMetrics();
    refreshDataMode();

    return () => {
      if (wsRef.current) wsRef.current.close();
      clearTimeout(reconnectTimer);
    };
  }, []);

  const switchDataMode = async (mode) => {
    try {
      // Mode must be sent as a query param, not a request body
      // api.post unwraps {ok,data} -> returns {status, mode, adapter}
      const res = await api.post(`/api/data/switch-mode?mode=${encodeURIComponent(mode)}`);
      // After unwrapping, res = {status: 'switched', mode: '...', adapter: '...'}
      if (res && res.mode) {
        setDataMode(res.mode);
      } else {
        setDataMode(mode);
      }
    } catch (err) {
      console.error('Failed to switch data mode:', err);
      throw err;
    }
  };

  const triggerTick = async () => {
    try {
      await api.post('/api/telemetry/tick');
    } catch (err) {
      console.error('Failed to trigger telemetry tick:', err);
      throw err;
    }
  };

  return (
    <AppContext.Provider
      value={{
        state: {
          telemetry,
          alerts,
          metrics,
          dataMode,
          open5gsHealth,
          isConnected,
          latestAlert,
        },
        refreshTelemetry,
        refreshMetrics,
        refreshAlerts,
        switchDataMode,
        triggerTick,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}
