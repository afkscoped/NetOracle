# NetOracle Training Guide

This guide covers training the Causal Temporal Graph Neural Network (CTGNN) on Google Colab (free T4 GPU) or local CUDA.

## Quick Start - Google Colab (Free T4 GPU)

### 1. Upload to Colab

1. Open [Google Colab](https://colab.research.google.com)
2. Create new notebook
3. Upload the training script:
   ```python
   from google.colab import files
   uploaded = files.upload()  # Select train_ctgnn_colab.py
   ```

### 2. Install Dependencies

```python
!pip install torch pandas scikit-learn tqdm matplotlib -q
```

### 3. Run Training

```python
!python train_ctgnn_colab.py --epochs 12 --batch-size 512 --hidden-dim 96
```

**T4 Optimization Tips:**
- Uses `torch.cuda.amp` automatic mixed precision (faster on T4)
- Batch size 512 fits comfortably in T4 16GB VRAM
- 12 epochs = ~3-5 minutes on T4
- Expected AUC: 0.82-0.88 on synthetic data

### 4. Download Trained Model

```python
from google.colab import files
files.download('artifacts/ctgnn_t4_best.pt')
files.download('artifacts/training_summary.json')
```

### 5. Use in NetOracle

Place the downloaded model in your NetOracle directory:
```bash
mkdir -p netoracle/artifacts
cp ctgnn_t4_best.pt netoracle/artifacts/
```

## Local CUDA Training

### Requirements

- NVIDIA GPU with CUDA support (GTX 1060 6GB+ or RTX series)
- CUDA 11.8+ and cuDNN installed
- Python 3.9+

### Setup

```bash
# Install PyTorch with CUDA
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Install other dependencies
pip install pandas scikit-learn tqdm matplotlib
```

### Run Training

```bash
cd netoracle/training
python train_ctgnn_colab.py --epochs 20 --batch-size 256 --hidden-dim 128
```

**Local GPU Tips:**
- Increase `--hidden-dim` to 128-256 for better capacity
- Use `--batch-size 256` or higher if you have 8GB+ VRAM
- Monitor with `nvidia-smi` during training

## Training Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--epochs` | 8 | Number of training epochs |
| `--batch-size` | 512 | Mini-batch size (reduce if OOM) |
| `--hidden-dim` | 96 | GRU hidden dimension |
| `--dropout` | 0.15 | Dropout rate |
| `--lr` | 3e-4 | Learning rate |
| `--window` | 12 | Time steps per sample |
| `--horizon` | 20 | Prediction horizon (minutes ahead) |
| `--cpu` | False | Force CPU training |

## Using Custom Data

### CSV Format

```csv
timestamp,slice_id,node_id,cpu,memory,latency_ms,packet_loss,throughput_mbps,prb_utilization,fault_label
2026-05-03T10:00:00Z,slice_1,upf_1,52,58,24,0.006,860,0.55,0
```

### Train on Custom Data

```python
!python train_ctgnn_colab.py --data /path/to/your/telemetry.csv --epochs 15
```

## Expected Results

### Benchmarks (Synthetic Data)

| Metric | Target | Typical Result |
|--------|--------|--------------|
| ROC-AUC | > 0.75 | 0.82-0.88 |
| Training Time (T4) | - | 3-5 min |
| Training Time (RTX 3060) | - | 2-3 min |

### Model Outputs

The trained model is saved as `ctgnn_t4_best.pt` with:
- `model_state_dict`: Trained weights
- `metrics`: Feature names and normalization stats
- `window`: Temporal window size
- `horizon`: Prediction horizon
- `auc`: Best validation AUC achieved

## Troubleshooting

### Out of Memory (OOM)

Reduce batch size:
```bash
python train_ctgnn_colab.py --batch-size 128
```

### CUDA Not Available

Check PyTorch installation:
```python
import torch
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0))
```

### Low AUC

- Increase `--epochs` to 20+
- Increase `--hidden-dim` to 128+
- Ensure sufficient fault labels in training data

## Next Steps

After training:
1. Download model from Colab/artifacts
2. Place in `netoracle/artifacts/`
3. Update NetOracle to load model for inference (optional enhancement)
4. Run benchmarks to validate: `POST /api/benchmarks/run`

## Architecture Details

The CTGNN uses:
- **GRU encoder**: Captures temporal dependencies
- **Multi-head attention**: Causal attention over time windows
- **BCE loss**: With class weighting for imbalanced faults
- **LayerNorm**: For training stability

The model architecture is optimized for:
- Fast inference (< 10ms per prediction)
- Small footprint (~2MB for 96 hidden dim)
- Robust generalization across fault types
