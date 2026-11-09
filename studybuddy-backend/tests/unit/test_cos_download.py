"""COS 素材下载契约测试。

回归 cos-python-sdk-v5 真实返回：get_object() 返回 response["Body"]（StreamBody），
下载方法为 get_stream_to_file()，不存在 raw_stream 键。
旧代码误用 response["raw_stream"] 导致 KeyError，素材识别失败、Agent 看不到内容。
"""
import asyncio
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.utils import cos


@pytest.fixture(autouse=True)
def _cos_enabled(monkeypatch):
    """让 download_to_temp 进入 COS 路径而非提前 RuntimeError。"""
    monkeypatch.setattr(cos.settings, "COS_SECRET_ID", "test-secret-id")
    monkeypatch.setattr(cos.settings, "COS_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(cos.settings, "COS_BUCKET", "test-bucket")
    monkeypatch.setattr(cos.settings, "COS_REGION", "ap-shanghai")
    cos.reset_circuit()
    yield
    cos.reset_circuit()


class TestDownloadToTemp:
    def test_downloads_via_body_get_stream_to_file(self):
        """SDK get_object 返回 response["Body"]，下载走 get_stream_to_file。"""
        body = MagicMock()

        def _write(path):
            Path(path).write_bytes(b"cos-image-bytes")

        body.get_stream_to_file.side_effect = _write
        client = MagicMock()
        client.get_object.return_value = {"Body": body}

        with patch("qcloud_cos.CosS3Client", return_value=client):
            path = asyncio.run(cos.download_to_temp("materials/2026/07/demo.png"))

        assert Path(path).read_bytes() == b"cos-image-bytes"
        body.get_stream_to_file.assert_called_once_with(path)
        client.get_object.assert_called_once_with(Bucket="test-bucket", Key="materials/2026/07/demo.png")

    def test_download_failure_removes_temp_file_and_records_circuit(self):
        """下载异常时删除临时文件、记录熔断失败、抛 RuntimeError。"""
        temp_paths = []
        body = MagicMock()

        def _fail(path):
            temp_paths.append(path)
            raise RuntimeError("simulated network error")

        body.get_stream_to_file.side_effect = _fail
        client = MagicMock()
        client.get_object.return_value = {"Body": body}

        with patch("qcloud_cos.CosS3Client", return_value=client):
            with pytest.raises(RuntimeError, match="COS 下载失败"):
                asyncio.run(cos.download_to_temp("materials/2026/07/bad.png"))

        assert len(temp_paths) == 1
        assert not os.path.exists(temp_paths[0])
        assert cos._circuit["failures"] == 1
