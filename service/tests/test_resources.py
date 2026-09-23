from pathlib import Path
import pytest
from mesemondo.config import ROOT
from mesemondo.media import file_digest, validate_frames, store_blob


def test_media_verification_does_not_read_whole_file(tmp_path, monkeypatch):
    # Construct many valid 32 kHz/64k/mono frame headers; only frame validation,
    # not a decoder fixture. Prohibit Path.read_bytes to catch whole-file reads.
    path=tmp_path/'many-frames.mp3'
    frame=bytes.fromhex('fffb58c0') + bytes(284)
    path.write_bytes(frame*10000)
    import hashlib
    expected=hashlib.sha256(frame*10000).hexdigest()
    def forbidden(*args):raise AssertionError('Whole-file read is forbidden')
    monkeypatch.setattr(Path,'read_bytes',forbidden)
    validate_frames(path)
    assert file_digest(path)==expected
    assert store_blob(path,tmp_path/'blobs')==expected
    assert store_blob(path,tmp_path/'blobs')==expected


@pytest.mark.parametrize('suffix',[b'\xff',bytes.fromhex('fffb58c0')])
def test_streamed_frame_validation_rejects_truncation(tmp_path,suffix):
    path=tmp_path/'truncated.mp3'
    path.write_bytes(bytes.fromhex('fffb58c0')+bytes(284)+suffix)
    with pytest.raises(ValueError):validate_frames(path)
