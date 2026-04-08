"""Tests for IntegratedProvider device detection and failsafe diagnostics."""

import sys
from unittest.mock import MagicMock, patch

from core.ai.providers.integrated_provider import _detect_device


def _mock_torch(cuda=False, mps=False):
    """Create a mock torch module with configurable accelerator support."""
    mod = MagicMock()
    mod.cuda.is_available.return_value = cuda
    backends = MagicMock()
    backends.mps.is_available.return_value = mps
    mod.backends = backends
    return mod


# ─── _detect_device ──────────────────────────────────────


def test_detect_device_cuda():
    """torch sees CUDA → use cuda."""
    torch = _mock_torch(cuda=True, mps=False)
    device, detail = _detect_device(torch)
    assert device == "cuda"
    assert "cuda" in detail.lower()
    assert "running on cuda" in detail


def test_detect_device_mps():
    """torch sees MPS → use mps."""
    torch = _mock_torch(cuda=False, mps=True)
    device, detail = _detect_device(torch)
    assert device == "mps"
    assert "mps" in detail.lower()
    assert "running on mps" in detail


def test_detect_device_cpu_pure():
    """No accelerator on system, no accelerator in torch → cpu."""
    torch = _mock_torch(cuda=False, mps=False)
    with (
        patch("core.ai.providers.integrated_provider._system_has_cuda", return_value=False),
        patch("core.ai.providers.integrated_provider._system_has_mps", return_value=False),
    ):
        device, detail = _detect_device(torch)
    assert device == "cpu"
    assert "system is cpu" in detail
    assert "running on cpu" in detail


def test_detect_device_cuda_mismatch():
    """System has NVIDIA GPU but torch not built with CUDA."""
    torch = _mock_torch(cuda=False, mps=False)
    with (
        patch("core.ai.providers.integrated_provider._system_has_cuda", return_value=True),
        patch("core.ai.providers.integrated_provider._system_has_mps", return_value=False),
    ):
        device, detail = _detect_device(torch)
    assert device == "cpu"
    assert "cuda device found" in detail
    assert "not built with CUDA" in detail
    assert "Falling back to cpu" in detail
    assert "Reinstall" in detail


def test_detect_device_mps_mismatch():
    """System is Apple Silicon but torch not built with MPS."""
    torch = _mock_torch(cuda=False, mps=False)
    with (
        patch("core.ai.providers.integrated_provider._system_has_cuda", return_value=False),
        patch("core.ai.providers.integrated_provider._system_has_mps", return_value=True),
    ):
        device, detail = _detect_device(torch)
    assert device == "cpu"
    assert "mps device found" in detail
    assert "not built with MPS" in detail
    assert "Falling back to cpu" in detail
    assert "Reinstall" in detail


# ─── discover: torch missing ─────────────────────────────


async def test_discover_torch_missing():
    """discover() fails clearly when torch is not installed."""
    with patch.dict(sys.modules, {"torch": None}):
        from core.ai.providers.integrated_provider import IntegratedProvider

        result = await IntegratedProvider.discover()

    assert result.available is False
    assert "torch not installed" in result.error
    assert "uv pip install torch" in result.error


# ─── discover: transformers missing ──────────────────────


async def test_discover_transformers_missing():
    """discover() fails clearly when transformers is not installed."""
    mock_torch = _mock_torch()
    with patch.dict(sys.modules, {"torch": mock_torch, "transformers": None}):
        from core.ai.providers.integrated_provider import IntegratedProvider

        result = await IntegratedProvider.discover()

    assert result.available is False
    assert "transformers not installed" in result.error
    assert "uv pip install" in result.error


# ─── discover: happy paths with detail ───────────────────


async def test_discover_cuda_has_detail():
    """discover() on CUDA system returns detail message."""
    mock_torch = _mock_torch(cuda=True, mps=False)
    mock_tf = MagicMock()
    with (
        patch.dict(sys.modules, {"torch": mock_torch, "transformers": mock_tf}),
        patch("core.ai.providers.integrated_provider._system_has_cuda", return_value=True),
    ):
        from core.ai.providers.integrated_provider import IntegratedProvider

        result = await IntegratedProvider.discover()

    assert result.available is True
    assert result.endpoint == "local:cuda"
    assert result.detail is not None
    assert "running on cuda" in result.detail


async def test_discover_mps_has_detail():
    """discover() on MPS system returns detail message."""
    mock_torch = _mock_torch(cuda=False, mps=True)
    mock_tf = MagicMock()
    with (
        patch.dict(sys.modules, {"torch": mock_torch, "transformers": mock_tf}),
        patch("core.ai.providers.integrated_provider._system_has_mps", return_value=True),
    ):
        from core.ai.providers.integrated_provider import IntegratedProvider

        result = await IntegratedProvider.discover()

    assert result.available is True
    assert result.endpoint == "local:mps"
    assert "running on mps" in result.detail


async def test_discover_cpu_has_detail():
    """discover() on CPU-only system returns detail message."""
    mock_torch = _mock_torch(cuda=False, mps=False)
    mock_tf = MagicMock()
    with (
        patch.dict(sys.modules, {"torch": mock_torch, "transformers": mock_tf}),
        patch("core.ai.providers.integrated_provider._system_has_cuda", return_value=False),
        patch("core.ai.providers.integrated_provider._system_has_mps", return_value=False),
    ):
        from core.ai.providers.integrated_provider import IntegratedProvider

        result = await IntegratedProvider.discover()

    assert result.available is True
    assert result.endpoint == "local:cpu"
    assert "system is cpu" in result.detail


async def test_discover_cuda_mismatch_still_available():
    """discover() still succeeds on mismatch (falls back to cpu), with warning."""
    mock_torch = _mock_torch(cuda=False, mps=False)
    mock_tf = MagicMock()
    with (
        patch.dict(sys.modules, {"torch": mock_torch, "transformers": mock_tf}),
        patch("core.ai.providers.integrated_provider._system_has_cuda", return_value=True),
        patch("core.ai.providers.integrated_provider._system_has_mps", return_value=False),
    ):
        from core.ai.providers.integrated_provider import IntegratedProvider

        result = await IntegratedProvider.discover()

    assert result.available is True
    assert result.endpoint == "local:cpu"
    assert "cuda device found" in result.detail
    assert "Falling back to cpu" in result.detail


# ─── _system_has_cuda / _system_has_mps ──────────────────


def test_system_has_cuda_with_nvidia_smi():
    """_system_has_cuda returns True when nvidia-smi is found and runs."""
    from core.ai.providers.integrated_provider import _system_has_cuda

    with (
        patch("shutil.which", return_value="/usr/bin/nvidia-smi"),
        patch("subprocess.run"),
    ):
        assert _system_has_cuda() is True


def test_system_has_cuda_no_nvidia_smi():
    """_system_has_cuda returns False when nvidia-smi not in PATH."""
    from core.ai.providers.integrated_provider import _system_has_cuda

    with patch("shutil.which", return_value=None):
        assert _system_has_cuda() is False


def test_system_has_cuda_nvidia_smi_fails():
    """_system_has_cuda returns False when nvidia-smi exists but crashes."""
    from core.ai.providers.integrated_provider import _system_has_cuda

    with (
        patch("shutil.which", return_value="/usr/bin/nvidia-smi"),
        patch("subprocess.run", side_effect=OSError("no such file")),
    ):
        assert _system_has_cuda() is False


def test_system_has_mps_on_darwin_arm64():
    """_system_has_mps returns True on macOS arm64."""
    from core.ai.providers.integrated_provider import _system_has_mps

    with (
        patch("platform.system", return_value="Darwin"),
        patch("platform.machine", return_value="arm64"),
    ):
        assert _system_has_mps() is True


def test_system_has_mps_on_darwin_x86():
    """_system_has_mps returns False on Intel Mac."""
    from core.ai.providers.integrated_provider import _system_has_mps

    with (
        patch("platform.system", return_value="Darwin"),
        patch("platform.machine", return_value="x86_64"),
    ):
        assert _system_has_mps() is False


def test_system_has_mps_on_linux():
    """_system_has_mps returns False on Linux."""
    from core.ai.providers.integrated_provider import _system_has_mps

    with patch("platform.system", return_value="Linux"):
        assert _system_has_mps() is False
