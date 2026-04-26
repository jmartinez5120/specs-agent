# Local install (no admin required)

For enterprise machines where you can't run DMG installers or use `sudo`, specs-agent installs entirely in your home directory with just Python 3.11+ available.

## One-command install

```bash
git clone https://github.com/<your-org>/specs-agent.git
cd specs-agent
./install.sh            # small model (~3 GB, Gemma 4 E4B-it)
# or: ./install.sh medium   (~10 GB, Gemma 4 26B-A4B-it)
# or: ./install.sh --no-ai  (skip AI, Faker only)
```

What it does:

| Step | Where it lands | Admin? |
|---|---|---|
| Creates Python venv | `~/.specs-agent-venv` | No |
| Installs package + deps | inside venv | No |
| Installs `llama-cpp-python` **with Metal GPU** | via pre-built wheel from PyPI | No |
| Downloads Gemma 4 GGUF | `~/.specs-agent/models/` | No |
| Writes config | `~/.specs-agent/config.yaml` | No |
| Creates launchers | `~/.local/bin/specs-agent-api`, `~/.local/bin/specs-agent` | No |

**Nothing** touches `/usr/local`, `/opt`, `/Library`, or anywhere that needs admin. No Xcode CLI tools, no Homebrew, no compiler toolchain — llama-cpp-python ships pre-compiled Metal wheels for Apple Silicon on PyPI.

## Requirements

- macOS 13+ (for bundled Python 3) **or** Python 3.11+ installed any other way
- Apple Silicon recommended (M1/M2/M3/M4) for Metal GPU acceleration
- Internet access (to PyPI + HuggingFace CDN)
- ~4 GB free disk for small model, ~12 GB for medium

If Python 3.11+ isn't on the machine and you can't install anything system-wide, use [pyenv](https://github.com/pyenv/pyenv) in your home directory, or download the official Python universal installer from python.org and install to `~/Library/Frameworks/` (user-only install option during setup).

## Running

```bash
# After install, if ~/.local/bin is on PATH:
specs-agent-api            # starts on http://localhost:8765

# Or invoke directly:
~/.local/bin/specs-agent-api
```

Then open `http://localhost:8765/docs` for the API, or open the Web UI (if deployed separately on a static host).

## Why this is faster than Docker

Running natively, `llama-cpp-python` uses your M-series chip's **Metal GPU** for inference. Docker on macOS can't access Metal — it runs pure CPU, which is 5-10x slower.

With `n_gpu_layers: -1` in the config (the default for the local install), every transformer layer runs on the GPU. On an M4 Pro:
- **Small model**: ~200 tok/s (vs ~40 tok/s in Docker CPU)
- **Medium model**: ~50-80 tok/s (vs ~15 tok/s in Docker CPU)

An 19-endpoint plan that takes 6 minutes in Docker runs in ~60-90 seconds natively.

## Uninstall

```bash
rm -rf ~/.specs-agent-venv ~/.specs-agent ~/.local/bin/specs-agent-api ~/.local/bin/specs-agent
```

Nothing to clean up system-wide.
