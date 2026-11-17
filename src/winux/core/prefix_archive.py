"""Strict, non-extracting inspector for Winux prefix backup containers."""
import hashlib, json, os, stat
from winux.core.prefix_backup import MAGIC, MAX_ARCHIVE, MAX_MANIFEST, CHUNK
from winux.core.prefix_filesystem import MAX_FILES, MAX_DIRECTORIES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, _validate_member_path

class PrefixArchiveError(ValueError):
    """Malformed, ambiguous, or unsafe backup container."""

class _BoundedHashReader:
    def __init__(self, fd, length): self.fd, self.remaining, self.digest = fd, length, hashlib.sha256()
    def read(self, size):
        if size < 0: raise PrefixArchiveError("Unbounded reads are forbidden")
        if self.remaining == 0: return b""
        data = os.read(self.fd, min(size, self.remaining))
        if not data: raise PrefixArchiveError("Truncated payload")
        self.remaining -= len(data); self.digest.update(data); return data
    def exact(self, size):
        chunks = []
        while size:
            chunk = self.read(min(size, CHUNK))
            if not chunk: raise PrefixArchiveError("Truncated payload")
            chunks.append(chunk); size -= len(chunk)
        return b"".join(chunks)
    def drain_zeroes(self):
        while self.remaining:
            if any(self.read(min(self.remaining, CHUNK))): raise PrefixArchiveError("Non-zero bytes after tar end marker")

def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise PrefixArchiveError("Duplicate JSON object key")
        result[key] = value
    return result
def _reject_constant(value): raise PrefixArchiveError("Non-finite JSON number")
def _octal(field, label):
    raw = field.rstrip(b"\0 ").lstrip(b" ")
    if not raw: return 0
    if any(byte < 48 or byte > 55 for byte in raw): raise PrefixArchiveError("Invalid tar " + label)
    return int(raw, 8)
def _tar_string(field): return field.split(b"\0", 1)[0].decode("utf-8", errors="strict")

def _read_ustar(payload):
    records, seen = [], set(); files = directories = total = 0; ended = False
    while payload.remaining:
        header = payload.exact(512)
        if header == bytes(512):
            if payload.exact(512) != bytes(512): raise PrefixArchiveError("Invalid tar end marker")
            ended = True; payload.drain_zeroes(); break
        stored = _octal(header[148:156], "checksum")
        actual = sum(header[:148]) + 8 * 32 + sum(header[156:])
        if stored != actual: raise PrefixArchiveError("Tar header checksum mismatch")
        if header[257:263] != b"ustar\0" or header[263:265] != b"00": raise PrefixArchiveError("Only strict USTAR headers are supported")
        flag = header[156:157]
        if flag in (b"\0", b"0"): kind = "file"
        elif flag == b"5": kind = "directory"
        else: raise PrefixArchiveError("Tar links, PAX, sparse, and special entries are forbidden")
        name, prefix = _tar_string(header[:100]), _tar_string(header[345:500])
        path = prefix + "/" + name if prefix else name
        if kind == "directory":
            if not path.endswith("/") or path.endswith("//"): raise PrefixArchiveError("Non-canonical USTAR directory name")
            path = path[:-1]
        elif path.endswith("/"):
            raise PrefixArchiveError("Regular file path has a trailing slash")
        try: normalized = _validate_member_path(path)
        except (ValueError, UnicodeError) as error: raise PrefixArchiveError("Unsafe tar member path") from error
        if normalized != path or path in seen: raise PrefixArchiveError("Duplicate or non-canonical tar path")
        seen.add(path); mode = _octal(header[100:108], "mode"); size = _octal(header[124:136], "size")
        if mode & ~0o777: raise PrefixArchiveError("Unsafe tar mode bits")
        if kind == "directory" and size: raise PrefixArchiveError("Directory entries cannot contain data")
        if kind == "file":
            files += 1; total += size
            if size > MAX_FILE_BYTES or files > MAX_FILES or total > MAX_TOTAL_BYTES: raise PrefixArchiveError("Tar resource limit exceeded")
        else:
            directories += 1
            if directories > MAX_DIRECTORIES: raise PrefixArchiveError("Tar directory limit exceeded")
        records.append({"path":path,"type":kind,"mode":mode & 0o755,"size":size})
        left = size
        while left:
            chunk = payload.exact(min(left, CHUNK)); left -= len(chunk)
        padding = (-size) % 512
        if padding and any(payload.exact(padding)): raise PrefixArchiveError("Non-zero tar padding")
    if not ended: raise PrefixArchiveError("Tar end marker is missing")
    return records, total

def inspect_prefix_backup(path=None, *, _fd=None):
    """Validate without extracting files, creating a prefix, or invoking Wine.

    When _fd is supplied, inspect a duplicate of that already-open file
    descriptor so callers can validate and later consume the same pinned file.
    """
    flags = os.O_RDONLY | getattr(os,"O_CLOEXEC",0) | getattr(os,"O_NOFOLLOW",0)
    fd = os.dup(_fd) if _fd is not None else os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1: raise PrefixArchiveError("Backup must be a single-link regular file")
        if before.st_size < len(MAGIC) + 16: raise PrefixArchiveError("Backup container is truncated")
        if os.read(fd, len(MAGIC)) != MAGIC: raise PrefixArchiveError("Unknown backup format")
        raw_len = os.read(fd, 8)
        if len(raw_len) != 8: raise PrefixArchiveError("Missing payload length")
        payload_len = int.from_bytes(raw_len, "big")
        if payload_len < 2048 or payload_len > MAX_ARCHIVE or payload_len > before.st_size: raise PrefixArchiveError("Payload length outside supported limits")
        payload = _BoundedHashReader(fd, payload_len); records, total = _read_ustar(payload)
        if payload.remaining: raise PrefixArchiveError("Payload was not fully consumed")
        raw_manifest_len = os.read(fd, 8)
        if len(raw_manifest_len) != 8: raise PrefixArchiveError("Missing manifest length")
        manifest_len = int.from_bytes(raw_manifest_len, "big")
        if not 0 < manifest_len <= MAX_MANIFEST: raise PrefixArchiveError("Manifest size outside supported limits")
        manifest_raw = bytearray()
        while len(manifest_raw) < manifest_len:
            chunk = os.read(fd, min(CHUNK, manifest_len-len(manifest_raw)))
            if not chunk: raise PrefixArchiveError("Truncated manifest")
            manifest_raw.extend(chunk)
        if os.read(fd, 1): raise PrefixArchiveError("Trailing bytes after manifest")
        try: manifest = json.loads(manifest_raw.decode("utf-8"), object_pairs_hook=_json_pairs, parse_constant=_reject_constant)
        except (UnicodeDecodeError, json.JSONDecodeError) as error: raise PrefixArchiveError("Invalid manifest JSON") from error
        required = {"format","format_version","architecture","runtime","files","directories","total_bytes","drive_mappings","payload","entries"}
        if not isinstance(manifest,dict) or set(manifest) != required: raise PrefixArchiveError("Manifest schema mismatch")
        if manifest["format"] != "winux-prefix-backup" or manifest["format_version"] != 1: raise PrefixArchiveError("Unsupported backup format")
        if manifest["architecture"] != "win64" or not isinstance(manifest["runtime"],str) or not manifest["runtime"]: raise PrefixArchiveError("Invalid runtime metadata")
        pm = manifest["payload"]
        if not isinstance(pm,dict) or set(pm) != {"name","size","sha256"} or pm["name"] != "payload.tar" or pm["size"] != payload_len: raise PrefixArchiveError("Payload metadata mismatch")
        digest = payload.digest.hexdigest()
        if pm["sha256"] != digest: raise PrefixArchiveError("Payload SHA-256 mismatch")
        if manifest["total_bytes"] != total or manifest["files"] != sum(x["type"]=="file" for x in records) or manifest["directories"] != sum(x["type"]=="directory" for x in records): raise PrefixArchiveError("Manifest counters mismatch")
        entries = manifest["entries"]
        if not isinstance(entries,list) or len(entries) != len(records): raise PrefixArchiveError("Manifest inventory mismatch")
        expected = []
        for entry in entries:
            if not isinstance(entry,dict) or not {"path","type","mode","size"} <= set(entry): raise PrefixArchiveError("Invalid inventory entry")
            expected.append({k:entry[k] for k in ("path","type","mode","size")})
        if expected != records: raise PrefixArchiveError("Manifest and tar inventory differ")
        by_path = {item["path"]: item for item in records}
        if by_path.get("drive_c", {}).get("type") != "directory" or by_path.get("dosdevices", {}).get("type") != "directory":
            raise PrefixArchiveError("Required Wine prefix directories are missing")
        if any(path.startswith("dosdevices/") for path in by_path):
            raise PrefixArchiveError("Drive mapping directory must not contain archived links")
        for item in records:
            parent = item["path"].rpartition("/")[0]
            if parent and by_path.get(parent, {}).get("type") != "directory":
                raise PrefixArchiveError("Archive member has no explicit directory parent")
        mappings = manifest["drive_mappings"]
        if not isinstance(mappings, dict) or set(mappings) != {"c", "z", "serial"}:
            raise PrefixArchiveError("Invalid logical drive mappings")
        if mappings["c"] != "drive_c" or mappings["z"] not in (None, "/") or mappings["serial"] not in (None, "wine-default"):
            raise PrefixArchiveError("Unsupported logical drive mapping")
        after = os.fstat(fd)
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) != (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns): raise PrefixArchiveError("Backup changed during inspection")
        return {"format_version":1,"architecture":manifest["architecture"],"runtime":manifest["runtime"],"files":manifest["files"],"directories":manifest["directories"],"total_bytes":total,"payload_sha256":digest,"drive_mappings":manifest["drive_mappings"],"entries":records}
    finally: os.close(fd)