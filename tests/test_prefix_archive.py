import hashlib, json, os, tempfile, unittest
from pathlib import Path
from winux.core.prefix_archive import PrefixArchiveError, inspect_prefix_backup
from winux.core.prefix_backup import MAGIC

def make_container(payload, manifest, path):
    encoded=json.dumps(manifest,separators=(",",":")).encode()
    Path(path).write_bytes(MAGIC+len(payload).to_bytes(8,"big")+payload+len(encoded).to_bytes(8,"big")+encoded)
def header(name,size,kind=b"0",mode=0o644):
    b=bytearray(512); raw=name.encode(); b[:len(raw)]=raw
    b[100:108]=f"{mode:07o}\0".encode(); b[108:116]=b"0000000\0"; b[116:124]=b"0000000\0"
    b[124:136]=f"{size:011o}\0".encode(); b[136:148]=b"00000000000\0"; b[148:156]=b"        "; b[156:157]=kind
    b[257:263]=b"ustar\0"; b[263:265]=b"00"; checksum=sum(b); b[148:156]=f"{checksum:06o}\0 ".encode(); return bytes(b)
def payload_ok():
    data=b"hello"; return header("drive_c/a.txt",len(data))+data+bytes(512-len(data))+bytes(1024)

class InspectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.path=Path(self.tmp.name)/"backup.wux"; p=payload_ok()
        self.manifest={"format":"winux-prefix-backup","format_version":1,"architecture":"win64","runtime":"wine-stable-11","files":1,"directories":0,"total_bytes":5,"drive_mappings":{"c":"drive_c","z":None,"serial":None},"payload":{"name":"payload.tar","size":len(p),"sha256":hashlib.sha256(p).hexdigest()},"entries":[{"path":"drive_c/a.txt","type":"file","mode":0o644,"size":5,"device":1,"inode":2,"mtime_ns":1,"ctime_ns":1,"nlink":1}]}
        make_container(p,self.manifest,self.path)
    def test_valid_inspection_has_no_extraction_side_effect(self):
        self.assertEqual(inspect_prefix_backup(self.path)["total_bytes"],5); self.assertEqual(list(Path(self.tmp.name).iterdir()),[self.path])
    def test_digest_mismatch(self):
        self.manifest["payload"]["sha256"]="0"*64; make_container(payload_ok(),self.manifest,self.path)
        with self.assertRaises(PrefixArchiveError): inspect_prefix_backup(self.path)
    def test_duplicate_json_key(self):
        p=payload_ok(); raw=b'{"format":"winux-prefix-backup","format":"evil"}'
        self.path.write_bytes(MAGIC+len(p).to_bytes(8,"big")+p+len(raw).to_bytes(8,"big")+raw)
        with self.assertRaises(PrefixArchiveError): inspect_prefix_backup(self.path)
    def test_symlink_archive_rejected(self):
        link=Path(self.tmp.name)/"link"; link.symlink_to(self.path)
        with self.assertRaises(OSError): inspect_prefix_backup(link)
    def test_traversal_path_rejected(self):
        p=header("../escape",0)+bytes(1024); self.manifest["payload"].update(size=len(p),sha256=hashlib.sha256(p).hexdigest()); self.manifest.update(files=1,total_bytes=0,entries=[{"path":"../escape","type":"file","mode":0o644,"size":0,"device":1,"inode":2,"mtime_ns":1,"ctime_ns":1,"nlink":1}]); make_container(p,self.manifest,self.path)
        with self.assertRaises(PrefixArchiveError): inspect_prefix_backup(self.path)

if __name__=="__main__": unittest.main()