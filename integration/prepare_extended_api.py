"""Fetch the exact upstream dependency without relying on BuildKit Git networking."""
import hashlib
import io
import tarfile
import urllib.request
from pathlib import Path

COMMIT='b49663dea326854a2323423eaeab7e7f54d325a7'
SHA256='cf25ac189433d9b1ccd10135498e7379f335ba017460474418d1f4858cc113e3'
URL='https://codeload.github.com/ertis-research/extended-api-for-eclipse-ditto/tar.gz/'+COMMIT

def prepare(root):
    target=(Path(root)/'integration/vendor/extended-api').resolve()
    marker=target/'.source-sha256'
    if marker.exists() and marker.read_text().strip()==SHA256 and (target/'package.json').is_file():return
    with urllib.request.urlopen(URL,timeout=60) as r:raw=r.read(8*1024*1024)
    if hashlib.sha256(raw).hexdigest()!=SHA256:raise RuntimeError('Extended API archive checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive.getmembers():
            parts=Path(member.name).parts
            if not parts or parts[0]!='extended-api-for-eclipse-ditto-'+COMMIT:raise RuntimeError('Unexpected archive root')
            dest=target.joinpath(*parts[1:]).resolve()
            if not dest.is_relative_to(target):raise RuntimeError('Unsafe archive path')
            if member.isdir():dest.mkdir(parents=True,exist_ok=True)
            elif member.isfile():
                dest.parent.mkdir(parents=True,exist_ok=True)
                with archive.extractfile(member) as f:dest.write_bytes(f.read())
            else:raise RuntimeError('Unexpected archive link')
    marker.write_text(SHA256+'\n')

if __name__=='__main__':prepare(Path(__file__).resolve().parent.parent)
