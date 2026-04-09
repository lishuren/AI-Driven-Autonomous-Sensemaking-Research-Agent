# graphragloader Runbook (Windows)

This runbook documents practical commands, known warnings, and troubleshooting
for large indexing runs (for example `D:\Mainstream` to `D:\mainstreamGraphRAG`).

## 1. Prerequisites

Run from repo root:

```powershell
cd D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent
.\.venv\Scripts\pip.exe install -e ".\graphragloader\.[all]"
```

Additional packages commonly needed in real datasets:

```powershell
.\.venv\Scripts\pip.exe install docx2txt pydub git+https://github.com/openai/whisper.git
```

Install ffmpeg/ffprobe (required by `pydub`):

```powershell
winget install --id Gyan.FFmpeg -e
```

Verify binaries are available:

```powershell
where ffmpeg
where ffprobe
ffmpeg -version
ffprobe -version
```

## 2. Known Good Index Commands

Use `standard` for best extraction quality:

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphragloader.exe" index `
  --source D:\Mainstream `
  --target D:\mainstreamGraphRAG `
  --include-code `
  --method standard `
  --provider ollama `
  --model gemma4:e4b `
  --embedding-model nomic-embed-text
```

Use `fast` for cheaper/faster first pass:

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphragloader.exe" index `
  --source D:\Mainstream `
  --target D:\mainstreamGraphRAG `
  --include-code `
  --method fast `
  --provider ollama `
  --model gemma4:e4b `
  --embedding-model nomic-embed-text
```

Notes:
- `standard` = LLM-heavy extraction (better quality, slower).
- `fast` = NLP-oriented extraction (faster, lower quality).
- Do not place `--verbose` at the end. Use `-v` before subcommands, e.g. `graphragloader -v index ...`.

## 3. Two-Step Workflow for Large Files

When files are too large and repeatedly truncated, convert first with a custom cap.

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphragloader.exe" convert `
  --source D:\Mainstream `
  --target D:\mainstreamGraphRAG `
  --include-code `
  --max-chars 500000
```

Then index existing input directly:

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphrag.exe" index `
  --root D:\mainstreamGraphRAG `
  --method standard
```

## 4. What Warnings Mean

### 4.1 `Please install pydub`
Audio/video support dependency missing. Install `pydub`.

### 4.2 `Please install OpenAI whisper model`
Whisper package missing for speech transcription from media files.

### 4.3 `Couldn't find ffprobe or avprobe`
Python package exists, but system binary is missing from PATH. Install ffmpeg.

### 4.4 `truncated <file> to 200000 chars`
Expected guardrail to control token/runtime costs. Increase `--max-chars` if needed.

### 4.5 `NativeCommandError` in PowerShell
This can appear when stderr output is treated as an exception while command is
still progressing. Check whether indexing actually continues before treating as
fatal.

### 4.6 `FP16 is not supported on CPU; using FP32 instead` (Whisper)

Whisper is transcribing audio/video files on **CPU** because a CUDA-capable
PyTorch was not found. The run will complete but is significantly slower
(~10-20x) than GPU-accelerated transcription.

**Why it happens**: The default `torch` installed with Whisper is the CPU-only
build.

**How to fix** — install the CUDA PyTorch wheel into the venv (requires
NVIDIA GPU + CUDA 12.x drivers):

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\pip.exe" install `
    torch torchvision torchaudio `
    --index-url https://download.pytorch.org/whl/cu124
```

After installation Whisper automatically detects the GPU and uses FP16.
Verify detection before re-running:

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\python.exe" -c `
    "import torch; print('CUDA:', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'n/a')"
```

Expected output when working: `CUDA: True | NVIDIA GeForce ...`

**If you do not have an NVIDIA GPU** the CPU warning is expected and harmless —
transcription will be slow but correct.

## 5. Process and Runtime Behavior

- Seeing 1-2 heavy Python processes during indexing is normal.
- Killing those processes is safe, but aborts current run.
- Large corpora can run for hours in `standard` mode.

Check active GraphRAG processes:

```powershell
tasklist | findstr /I graphragloader
tasklist | findstr /I graphrag
```

For a target-aware PowerShell check, run:

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\graphragloader\check_status.ps1" D:\mainstreamGraphRAG
```

If you are using Git Bash, WSL, or another Unix shell, you can also inspect a
specific GraphRAG target with:

```bash
./check_status.sh /path/to/graphrag-project
```

The script reports whether a matching indexing process is active and summarizes
the current `input/`, `output/`, `settings.yaml`, and `.graphragloader_state.json`
state for the target directory.

`check_status.ps1` prints the same status summary for Windows PowerShell and
PowerShell 7 terminals.

## 6. Quick Health Checks

Verify converted input exists:

```powershell
(Get-ChildItem D:\mainstreamGraphRAG\input -Filter *.txt).Count
```

Check output artifacts:

```powershell
Get-ChildItem D:\mainstreamGraphRAG\output -Recurse |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 15 Name, LastWriteTime, Length
```

## 7. Minimal Recovery Flow

If run state is unclear:

1. Stop stuck graphrag processes.
2. Re-run `convert` (optionally with `--max-chars`).
3. Re-run `index` using one command (no extra pipe wrappers).
4. Run a simple query after index finishes.

Query example:

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphragloader.exe" query `
  --target D:\mainstreamGraphRAG `
  --method global `
  --question "Summarize the key components and data flow." `
  --response-type "Detailed Report"
```
