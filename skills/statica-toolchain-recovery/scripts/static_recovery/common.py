"""Shared, side-effect-free helpers for the recovery workflow."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


class RecoveryError(Exception):
    """A classified workflow failure that is safe to show to a user."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass(frozen=True)
class TextDocument:
    text: str
    encoding: str
    bom: bytes
    newline: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_is_alive(pid: int) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        get_exit_code = kernel32.GetExitCodeProcess
        get_exit_code.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        get_exit_code.restype = wintypes.BOOL
        handle = open_process(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            exit_code = wintypes.DWORD()
            queried = bool(get_exit_code(handle, ctypes.byref(exit_code)))
            close_handle(handle)
            return not queried or exit_code.value == 259  # Query failure is conservatively live.
        return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED means the process exists.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _lock_owner_pid(raw: bytes) -> int | None:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        try:
            return int(raw.decode("ascii").strip())
        except (UnicodeDecodeError, ValueError):
            return None
    pid = value.get("pid") if isinstance(value, dict) else None
    return pid if isinstance(pid, int) and not isinstance(pid, bool) else None


@contextmanager
def exclusive_file_lock(
    path: str | Path,
    *,
    owner: str,
    busy_code: str,
    busy_message: str,
) -> Iterator[None]:
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"pid": os.getpid(), "owner": owner, "created_at": utc_now(), "nonce": secrets.token_hex(16)},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    pending_descriptor, pending_name = tempfile.mkstemp(
        # Keep the publication source outside the protected tree. If the
        # owner is hard-killed between link() and unlink(), integrity scans of
        # that tree still see only the canonical lock name (which they omit).
        prefix=f".{lock_path.parent.name}.{lock_path.name}.pending-",
        dir=lock_path.parent.parent,
    )
    pending_path = Path(pending_name)
    acquired = False
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(pending_descriptor, payload[offset:])
            if written <= 0:
                raise OSError("lock payload write made no progress")
            offset += written
        os.fsync(pending_descriptor)
        os.close(pending_descriptor)
        pending_descriptor = -1

        for attempt in range(2):
            try:
                # A hard link publishes an already-complete payload without replacing
                # another process's lock. Source and destination share one directory.
                acquired = True
                os.link(pending_path, lock_path)
                pending_path.unlink()
                break
            except FileExistsError as exc:
                try:
                    existing = lock_path.read_bytes()
                    age_seconds = max(0.0, time.time() - lock_path.stat().st_mtime)
                except OSError:
                    raise RecoveryError(busy_code, f"{busy_message}: {lock_path}") from exc
                stale_pid = _lock_owner_pid(existing)
                corrupt_lock_is_old = stale_pid is None and age_seconds >= 30.0
                if attempt > 0 or (not corrupt_lock_is_old and (stale_pid is None or process_is_alive(stale_pid))):
                    raise RecoveryError(busy_code, f"{busy_message}: {lock_path}") from exc
                try:
                    if lock_path.read_bytes() != existing:
                        raise RecoveryError(busy_code, f"{busy_message}: {lock_path}")
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError as remove_exc:
                    raise RecoveryError(busy_code, f"{busy_message}: {lock_path}") from remove_exc
            except OSError as exc:
                raise RecoveryError(busy_code, f"잠금 파일을 만들 수 없음: {lock_path}") from exc
        if not acquired:
            raise RecoveryError(busy_code, f"{busy_message}: {lock_path}")
        try:
            yield
        finally:
            try:
                if lock_path.read_bytes() == payload:
                    lock_path.unlink()
            except OSError:
                # A leftover owned lock is recoverable from its dead PID on the
                # next invocation; cleanup failure must not mask the real result.
                pass
    finally:
        if pending_descriptor >= 0:
            os.close(pending_descriptor)
        if acquired:
            try:
                if lock_path.read_bytes() == payload:
                    lock_path.unlink()
            except OSError:
                pass
        try:
            pending_path.unlink()
        except OSError:
            pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(raw.encode("utf-8"))


def read_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise RecoveryError("InvalidJson", f"JSON 문서를 읽을 수 없음: {path}") from exc
    if not isinstance(value, dict):
        raise RecoveryError("InvalidJson", "JSON 최상위 값은 객체여야 함.")
    return value


def write_json(path: str | Path, value: Any) -> None:
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(path, raw)


def contained(path: str | Path, root: str | Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def require_contained(path: str | Path, root: str | Path) -> Path:
    resolved = Path(path).resolve()
    if not contained(resolved, root):
        raise RecoveryError("UnsafePath", f"허용된 경로를 벗어남: {resolved}")
    return resolved


def reject_link(path: Path) -> None:
    info = path.lstat()
    is_reparse = bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    if path.is_symlink() or is_reparse:
        raise RecoveryError("UnsafePath", f"링크 또는 reparse point는 지원하지 않음: {path}")


def reject_link_chain(path: str | Path) -> None:
    """Reject a link at the target or in any existing parent component."""
    absolute = Path(os.path.abspath(str(path)))
    for entry in (absolute, *absolute.parents):
        if os.path.lexists(entry):
            reject_link(entry)


def iter_files(root: str | Path) -> list[Path]:
    root = Path(root)
    reject_link(root)
    if root.is_file():
        return [root]
    result: list[Path] = []
    for directory, directories, names in os.walk(root, followlinks=False):
        for name in [*directories, *names]:
            entry = Path(directory) / name
            reject_link(entry)
            if entry.is_file():
                result.append(entry)
            elif not entry.is_dir():
                raise RecoveryError("UnsafePath", f"지원하지 않는 파일 항목: {entry}")
    return sorted(result, key=lambda item: str(item).casefold())


def tree_hashes(
    root: str | Path,
    *,
    absolute: bool = False,
    exclude_names: Iterable[str] = (),
) -> dict[str, str]:
    root = Path(root).resolve()
    excluded = {name.casefold() for name in exclude_names}
    return {
        str(path.resolve()) if absolute else path.relative_to(root).as_posix(): sha256_file(path)
        for path in iter_files(root)
        if path.name.casefold() not in excluded
    }


def assert_hashes(root: str | Path, hashes: dict[str, str], *, absolute: bool = False) -> None:
    root = Path(root).resolve()
    try:
        current = tree_hashes(root, absolute=absolute)
    except (OSError, RecoveryError) as exc:
        raise RecoveryError(
            "OriginalChanged",
            f"원본 파일 집합을 다시 읽을 수 없음: {root}",
            {"error": str(exc)},
        ) from exc
    expected_names = set(hashes)
    current_names = set(current)
    added = sorted(current_names - expected_names, key=str.casefold)
    removed = sorted(expected_names - current_names, key=str.casefold)
    changed = sorted(
        (name for name in expected_names & current_names if current[name] != hashes[name]),
        key=str.casefold,
    )
    if added or removed or changed:
        raise RecoveryError(
            "OriginalChanged",
            f"원본 파일 집합 또는 내용이 바뀜: {root}",
            {"added": added, "removed": removed, "changed": changed},
        )


def read_text_preserved(path: str | Path) -> TextDocument:
    raw = Path(path).read_bytes()
    bom = b""
    if raw.startswith(b"\xef\xbb\xbf"):
        bom, body, encoding = b"\xef\xbb\xbf", raw[3:], "utf-8"
    elif raw.startswith(b"\xff\xfe"):
        bom, body, encoding = b"\xff\xfe", raw[2:], "utf-16-le"
    elif raw.startswith(b"\xfe\xff"):
        bom, body, encoding = b"\xfe\xff", raw[2:], "utf-16-be"
    else:
        body = raw
        for candidate in ("utf-8", "cp949"):
            try:
                text = body.decode(candidate)
                encoding = candidate
                break
            except UnicodeDecodeError:
                continue
        else:
            raise RecoveryError("UnsupportedEncoding", f"손실 없이 읽을 수 없는 텍스트: {path}")
        newline = detect_newline(text)
        return TextDocument(text=text, encoding=encoding, bom=bom, newline=newline)
    try:
        text = body.decode(encoding)
    except UnicodeDecodeError as exc:
        raise RecoveryError("UnsupportedEncoding", f"손실 없이 읽을 수 없는 텍스트: {path}") from exc
    return TextDocument(text=text, encoding=encoding, bom=bom, newline=detect_newline(text))


def detect_newline(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    kinds = sum(bool(count) for count in (crlf, lf, cr))
    if kinds > 1:
        return "mixed"
    if crlf:
        return "\r\n"
    if lf:
        return "\n"
    if cr:
        return "\r"
    return ""


def encode_text_preserved(document: TextDocument, text: str) -> bytes:
    try:
        return document.bom + text.encode(document.encoding)
    except UnicodeEncodeError as exc:
        raise RecoveryError("UnsupportedEncoding", "변경 내용을 원래 인코딩으로 저장할 수 없음.") from exc


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.writing-",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        stream = os.fdopen(descriptor, "wb")
        descriptor = -1
        with stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except OSError:
            pass


def decode_output(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _x500_attributes(subject: str) -> list[tuple[str, str]] | None:
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    escaped = False
    for character in subject:
        if escaped:
            current.append("\\")
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"':
            quoted = not quoted
            current.append(character)
        elif character in {",", ";"} and not quoted:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if escaped or quoted:
        return None
    parts.append("".join(current).strip())

    attributes: list[tuple[str, str]] = []
    for part in parts:
        key, separator, raw_value = part.partition("=")
        key = key.strip().casefold()
        value = raw_value.strip()
        if not separator or not key or not value:
            return None
        if value.startswith('"'):
            if not value.endswith('"') or len(value) < 2:
                return None
            value = value[1:-1]
        elif '"' in value:
            return None
        decoded: list[str] = []
        index = 0
        while index < len(value):
            if value[index] != "\\":
                decoded.append(value[index])
                index += 1
                continue
            if index + 1 >= len(value):
                return None
            decoded.append(value[index + 1])
            index += 2
        attributes.append((key, "".join(decoded).strip()))
    return attributes


def is_trusted_suresofttech_signature(
    status: Any,
    subject: Any,
    signer_name: Any,
    thumbprint: Any,
) -> bool:
    """Accept a valid chain only for the exact Suresofttech publisher identity."""
    if status != "Valid" or not all(isinstance(value, str) for value in (subject, signer_name, thumbprint)):
        return False
    expected_name = "suresofttech inc."
    if signer_name.strip().casefold() != expected_name:
        return False
    attributes = _x500_attributes(subject)
    if attributes is None:
        return False
    common_names = [value.casefold() for key, value in attributes if key == "cn"]
    organizations = [value.casefold() for key, value in attributes if key == "o"]
    if common_names != [expected_name] or organizations != [expected_name]:
        return False
    return re.fullmatch(r"[0-9a-f]{40,64}", thumbprint.strip(), re.IGNORECASE) is not None


def _system_windows_directory() -> Path:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    getter = kernel32.GetSystemWindowsDirectoryW
    getter.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    getter.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = getter(buffer, len(buffer))
    if length == 0 or length >= len(buffer):
        raise OSError(ctypes.get_last_error(), "GetSystemWindowsDirectoryW failed")
    return Path(buffer.value).resolve()


def authenticode_info(path: str | Path) -> dict[str, Any]:
    """Read a Windows Authenticode signature without interpolating the path into code."""
    target = Path(path).resolve()
    if os.name != "nt":
        return {"valid": False, "status": "UnsupportedHost", "subject": None, "thumbprint": None}
    try:
        windows_directory = _system_windows_directory()
    except OSError:
        return {"valid": False, "status": "WindowsDirectoryUnavailable", "subject": None, "thumbprint": None}
    powershell = windows_directory / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not powershell.is_file():
        return {"valid": False, "status": "PowerShellUnavailable", "subject": None, "thumbprint": None}
    signature_env = os.environ.copy()
    signature_env["SystemRoot"] = str(windows_directory)
    signature_env["windir"] = str(windows_directory)
    signature_env["STATIC_RECOVERY_SIGNATURE_PATH"] = str(target)
    # Codex와 개발 셸이 주입한 PowerShell Core 모듈이 Windows PowerShell의
    # Microsoft.PowerShell.Security 모듈을 가리는 경우가 있다. 서명 확인에는
    # OS가 설치한 Windows PowerShell 모듈만 사용한다.
    signature_env["PSModulePath"] = str(powershell.parent / "Modules")
    script = (
        "$s=Get-AuthenticodeSignature -LiteralPath "
        "([Environment]::GetEnvironmentVariable('STATIC_RECOVERY_SIGNATURE_PATH'));"
        "$c=$s.SignerCertificate;$subject=$null;$signerName=$null;$issuer=$null;$thumbprint=$null;"
        "if($null -ne $c){$subject=$c.Subject;"
        "$signerName=$c.GetNameInfo([System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName,$false);"
        "$issuer=$c.Issuer;$thumbprint=$c.Thumbprint};"
        "[pscustomobject]@{status=[string]$s.Status;subject=$subject;signerName=$signerName;"
        "issuer=$issuer;thumbprint=$thumbprint}|ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            env=signature_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            shell=False,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"valid": False, "status": "SignatureCheckFailed", "subject": None, "thumbprint": None, "error": str(exc)}
    if completed.returncode != 0:
        return {
            "valid": False,
            "status": "SignatureCheckFailed",
            "subject": None,
            "thumbprint": None,
            "error": decode_output(completed.stderr)[:500],
        }
    try:
        value = json.loads(decode_output(completed.stdout))
    except (TypeError, ValueError):
        return {
            "valid": False,
            "status": "SignatureCheckFailed",
            "subject": None,
            "thumbprint": None,
            "error": decode_output(completed.stderr)[:500],
        }
    subject = value.get("subject") if isinstance(value, dict) else None
    status_value = value.get("status") if isinstance(value, dict) else None
    signer_name = value.get("signerName") if isinstance(value, dict) else None
    thumbprint = value.get("thumbprint") if isinstance(value, dict) else None
    return {
        "valid": is_trusted_suresofttech_signature(status_value, subject, signer_name, thumbprint),
        "status": status_value,
        "subject": subject,
        "signer_name": signer_name,
        "issuer": value.get("issuer") if isinstance(value, dict) else None,
        "thumbprint": thumbprint,
    }


def unique_child(parent: Path, prefix: str, existing: Iterable[str] = ()) -> Path:
    reserved = set(existing)
    for number in range(1, 10_000):
        name = f"{prefix}-{number:03d}"
        candidate = parent / name
        if name not in reserved and not candidate.exists():
            return candidate
    raise RecoveryError("WorkspaceLimit", f"새 {prefix} 작업 폴더를 만들 수 없음.")
