# MP4 转文字 & AI 润色

基于 Whisper Large-v3 语音识别 + MiniMax AI 润色的本地工具。

## 功能

- 🎬 支持 MP4, MOV, MKV, AVI 等视频格式
- 🎵 支持 MP3, WAV, M4A 等音频格式
- 📝 Whisper Large-v3 模型，中文识别精度高
- ✨ MiniMax AI 智能润色，修正错别字、优化标点
- 📋 支持复制和导出 TXT 文件
- 🎨 iOS 风格界面，进度实时显示

## 环境要求

- Python 3.8+
- NVIDIA 显卡（推荐，GPU 加速）
- FFmpeg（自动处理）

## 安装

### 1. 安装依赖

```bash
cd E:/project-repo/mp4-to-word
pip install -r requirements.txt
```

### 2. 配置 MiniMax API

在项目根目录创建 `.env` 文件：

```
MINIMAX_API_KEY=你的MiniMax API密钥
MINIMAX_GROUP_ID=你的Group ID
```

获取地址：https://www.minimaxi.com/user-center/basic-information/interface-key

### 3. 下载 Whisper 模型

```bash
# 使用 modelscope 下载（推荐国内用户）
pip install modelscope
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('AI-ModelScope/whisper-large-v3', cache_dir='E:/project-repo/mp4-to-word/models')"
```

模型会自动下载到 `models/AI-ModelScope/whisper-large-v3` 目录。

## 运行

```bash
python app.py
```

然后打开浏览器访问：http://localhost:5000

## AI 润色说明

AI 润色功能会：
1. 修正语音识别错误（错别字、同音字）
2. 补充和完善标点符号
3. 优化口语化表达，使其更书面化
4. 合理分段，使结构清晰
5. 保持原文含义，不添加新内容

## 项目结构

```
mp4-to-word/
├── app.py              # Flask Web 服务
├── transcribe.py       # Whisper 语音识别
├── polisher.py         # MiniMax AI 润色
├── templates/
│   └── index.html     # 前端页面
├── static/
│   └── style.css      # iOS 风格样式
├── models/             # Whisper 模型目录
├── uploads/           # 临时上传目录
├── outputs/           # 输出文件目录
├── requirements.txt   # Python 依赖
├── .env               # API 配置（需创建）
└── README.md
```

## 常见问题

### Q: 报错 "ffmpeg not found"
A: 确保 ffmpeg 在系统 PATH 中，或复制 `imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe` 到 `Python313/Scripts/ffmpeg.exe`

### Q: GPU 不工作
A: 确保安装了 CUDA 版本的 PyTorch：
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

### Q: 润色失败
A: 检查 MiniMax API Key 和 Group ID 是否配置正确
