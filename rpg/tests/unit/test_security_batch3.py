"""test_security_batch3.py — 安全审计 Batch 3 回归测试(认证凭据生命周期)。

无 DB 依赖的纯逻辑校验:
- 注册密文与验证码记录绑定，不同记录不能解密；不完整凭据拒绝。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class PendingRegisterStore(unittest.TestCase):
    def test_encrypted_registration_is_bound_to_verification_record(self):
        from platform_app import auth
        from utils.crypto import encrypt_api_key
        payload = {"username": "alice", "password_hash": "$argon2id$xxx", "birthday": "2000-01-01"}
        encrypted = encrypt_api_key(auth._encode_pending_register(payload), 0, "registration:1")
        self.assertNotIn(b"alice", encrypted)
        self.assertEqual(auth._registration_payload({"id": 1, "pending_payload": encrypted}), payload)
        with self.assertRaises(ValueError):
            auth._registration_payload({"id": 2, "pending_payload": encrypted})
        with self.assertRaises(ValueError):
            auth._registration_payload({"id": 1, "pending_payload": None})

    def test_decode_rejects_incomplete(self):
        from platform_app import auth
        # 缺 password_hash → None(防半残 payload)
        bad = auth._encode_pending_register({"username": "x", "birthday": "2000-01-01"})
        self.assertIsNone(auth._decode_pending_register(bad))


if __name__ == "__main__":
    unittest.main()
