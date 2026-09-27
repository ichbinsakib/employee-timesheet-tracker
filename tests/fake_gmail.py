"""A minimal stand-in for googleapiclient's Gmail service, for offline tests."""
import base64
import time


class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeGmail:
    def __init__(self):
        self._msgs = {}  # id -> dict
        self._atts = {}  # (msg_id, att_id) -> bytes
        self.list_calls = []

    def add_message(self, msg_id, sender, subject, files, ts=None):
        """files: list of (filename, bytes)."""
        parts = [{"mimeType": "text/plain", "filename": "", "body": {"size": 5, "data": "aGVsbG8"}}]
        for i, (fname, content) in enumerate(files):
            att_id = f"att{i}"
            self._atts[(msg_id, att_id)] = content
            parts.append({"filename": fname, "mimeType": "application/octet-stream",
                          "body": {"attachmentId": att_id, "size": len(content)}})
        self._msgs[msg_id] = {
            "id": msg_id, "threadId": "t" + msg_id,
            "internalDate": str(int((ts or time.time()) * 1000)),
            "payload": {"mimeType": "multipart/mixed", "headers": [
                {"name": "From", "value": f"Someone <{sender}>"}, {"name": "Subject", "value": subject}],
                "parts": parts},
        }

    # --- API surface used by GmailClient
    def users(self):
        return self

    def messages(self):
        return self

    def list(self, userId, q, maxResults):
        self.list_calls.append(q)
        ids = [{"id": m} for m in reversed(list(self._msgs))]  # newest first like Gmail
        return _Req(lambda: {"messages": ids})

    def list_next(self, req, resp):
        return None

    def get(self, userId, id, format=None, messageId=None):
        if messageId is not None:  # attachments().get
            data = self._atts[(messageId, id)]
            return _Req(lambda: {"data": base64.urlsafe_b64encode(data).decode().rstrip("=")})
        return _Req(lambda: self._msgs[id])

    def attachments(self):
        return self
