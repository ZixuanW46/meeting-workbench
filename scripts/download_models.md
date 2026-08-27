# M16 本地模型准备（仅 macOS）

首选直接运行公开模型下载脚本：

```bash
./scripts/download_models.sh
```

脚本只在 macOS 下载，不执行 Hugging Face 登录，也不需要 token；若已设置
`HF_ENDPOINT` 会原样尊重。模型放进 `MW_DATA_DIR` 下的 `models/`；未设置
`MW_DATA_DIR` 时就是仓库内的 `data/models/`。Linux 测试机可先预览命令：

```bash
DRY_RUN=1 ./scripts/download_models.sh
```

脚本还识别 `MW_FORCE_DARWIN=1`，但它仅供自动化测试覆盖非 DRY 的 Darwin
分支，不应在生产安装中设置。

最终目录必须是：

```text
data/models/
├── qwen3-asr-mlx/
│   ├── config.json
│   ├── tokenizer.json（以及模型仓库里的其他 tokenizer/config 文件）
│   └── *.safetensors（保留模型仓库原有的全部分片和索引）
└── sherpa-onnx/
    ├── segmentation.onnx
    └── embedding.onnx
```

## Qwen3-ASR MLX

若自动脚本不可用，可手动下载 mlx-audio 支持的 Qwen3-ASR MLX 模型仓库完整内容，例如
`mlx-community/Qwen3-ASR-1.7B-8bit`，原样放到
`data/models/qwen3-asr-mlx/`。不要只复制某一个 safetensors 分片；
`config.json`、tokenizer 文件、全部权重分片和索引必须在同一目录。

模型来源与文件清单以 mlx-audio 的 Qwen3-ASR 文档和对应模型仓库为准：

- <https://github.com/Blaizzy/mlx-audio/tree/main/mlx_audio/stt/models/qwen3_asr>
- <https://huggingface.co/mlx-community/Qwen3-ASR-1.7B-8bit/tree/main>

## sherpa-onnx 说话人模型

若自动脚本不可用，可手动下载两个 ONNX 文件，并按代码读取的固定名称落盘：

1. Pyannote segmentation 3.0 的 `model.onnx`，改名为
   `data/models/sherpa-onnx/segmentation.onnx`。
2. 3D-Speaker 中文 16 kHz 声纹模型
   `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx`，改名为
   `data/models/sherpa-onnx/embedding.onnx`。

直接下载地址：

- <https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2>
- <https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx>

## 本机检查

在 Apple Silicon Mac 上安装条件依赖后，显式选择真实后端并运行冒烟脚本：

```bash
.venv/bin/pip install -e ".[mac]"
export MW_ASR_BACKEND=qwen3-asr-mlx
export MW_DIARIZATION_BACKEND=sherpa-onnx
export MW_EMBEDDING_BACKEND=sherpa-onnx
./scripts/smoke_real_models.sh /path/to/local-test.wav
```

脚本只读本地音频和上述本地模型目录，不会下载权重，也不会把音频发送到云端。
