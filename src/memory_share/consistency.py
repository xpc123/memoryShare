"""Consistency layer: NFS-safe locking, CAS, idempotency."""

from __future__ import annotations

import contextlib
import hashlib
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .storage import StorageEngine


class ConsistencyError(Exception):
    """Raised when consistency checks fail."""


class IdempotencyStore:
    """In-memory store for idempotency keys (with optional persistence)."""

    def __init__(self, storage: StorageEngine):
        """Initialize idempotency store.

        Args:
            storage: Storage engine instance
        """
        self.storage = storage
        self._cache: dict[str, tuple[Any, float]] = {}  # key -> (result, timestamp)
        self._cache_ttl = 3600  # 1 hour

    def get(self, key: str) -> Optional[Any]:
        """Get cached result for idempotency key.

        Args:
            key: Idempotency key

        Returns:
            Cached result if exists and not expired, None otherwise
        """
        if key not in self._cache:
            return None

        result, timestamp = self._cache[key]
        if time.time() - timestamp > self._cache_ttl:
            del self._cache[key]
            return None

        return result

    def set(self, key: str, result: Any) -> None:
        """Cache result for idempotency key.

        Args:
            key: Idempotency key
            result: Result to cache
        """
        self._cache[key] = (result, time.time())

    def clear_expired(self) -> None:
        """Clear expired entries from cache."""
        now = time.time()
        expired_keys = [
            k for k, (_, ts) in self._cache.items()
            if now - ts > self._cache_ttl
        ]
        for key in expired_keys:
            del self._cache[key]


class ConsistencyLayer:
    """Consistency layer providing locking, CAS, and idempotency."""

    def __init__(self, storage: StorageEngine):
        """Initialize consistency layer.

        Args:
            storage: Storage engine instance
        """
        self.storage = storage
        self.idempotency = IdempotencyStore(storage)

    @contextlib.contextmanager
    def lock(self, timeout: float = 5.0):
        """Context manager for acquiring/releasing lock.

        Args:
            timeout: Maximum time to wait for lock

        Yields:
            None (lock is held during context)

        Raises:
            TimeoutError: If lock cannot be acquired
        """
        self.storage.acquire_lock(timeout)
        try:
            yield
        finally:
            self.storage.release_lock()

    def cas_state(
        self,
        expected_version: int,
        update_fn: Callable[[Any], Any],
        max_retries: int = 3,
    ) -> tuple[bool, Any]:
        """Compare-and-swap for state.json.

        Args:
            expected_version: Expected current version
            update_fn: Function that takes current state and returns new state
            max_retries: Maximum number of retry attempts

        Returns:
            (success, new_state_or_error)
        """
        for attempt in range(max_retries):
            with self.lock():
                state = self.storage.read_state()
                if state.version != expected_version:
                    if attempt < max_retries - 1:
                        # Exponential backoff
                        time.sleep(0.1 * (2 ** attempt))
                        continue
                    return False, ConsistencyError(
                        f"Version mismatch: expected {expected_version}, "
                        f"got {state.version}"
                    )

                # Update state
                new_state = update_fn(state)
                self.storage.write_state(new_state)
                return True, new_state

        return False, ConsistencyError("Max retries exceeded")

    def cas_with_idempotency(
        self,
        idempotency_key: str,
        expected_version: int,
        update_fn: Callable[[Any], Any],
        max_retries: int = 3,
    ) -> tuple[bool, Any]:
        """CAS with idempotency check.

        Args:
            idempotency_key: Idempotency key for deduplication
            expected_version: Expected current version
            update_fn: Function that takes current state and returns new state
            max_retries: Maximum number of retry attempts

        Returns:
            (success, result_or_error)
        """
        # Check idempotency first
        cached_result = self.idempotency.get(idempotency_key)
        if cached_result is not None:
            return True, cached_result

        # Perform CAS
        success, result = self.cas_state(expected_version, update_fn, max_retries)
        if success:
            # Cache result
            self.idempotency.set(idempotency_key, result)

        return success, result

    def generate_idempotency_key(
        self,
        source: str,
        session_id: Optional[str],
        checkpoint_range: Optional[tuple[int, int]],
        summary_hash: Optional[str] = None,
    ) -> str:
        """Generate idempotency key for an operation.

        Args:
            source: Source IDE
            session_id: Session ID
            checkpoint_range: (start_version, end_version) tuple
            summary_hash: Optional hash of summary content

        Returns:
            Idempotency key string
        """
        parts = [source]
        if session_id:
            parts.append(session_id)
        if checkpoint_range:
            parts.append(f"checkpoint_{checkpoint_range[0]}_{checkpoint_range[1]}")
        if summary_hash:
            parts.append(summary_hash[:8])

        key_str = ":".join(parts)
        return hashlib.sha256(key_str.encode()).hexdigest()[:32]

    def check_and_fix_consistency(self) -> tuple[bool, Optional[str]]:
        """Check and fix consistency issues.

        Returns:
            (is_consistent, error_message_or_none)
        """
        return self.storage.check_consistency()
