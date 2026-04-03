"""Sequence models — LSTM / GRU for time-series prediction.

Optional: only used if PyTorch is installed.
Falls back gracefully when torch is not available.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from app.models.baselines import BaseModel

logger = logging.getLogger(__name__)

_TORCH_AVAILABLE = False
try:
    import torch
    import torch.nn as nn
    _TORCH_AVAILABLE = True
except ImportError:
    pass


if _TORCH_AVAILABLE:
    class _LSTMNet(nn.Module):
        def __init__(self, input_dim: int, hidden_dim: int = 64, num_layers: int = 2, dropout: float = 0.2):
            super().__init__()
            self.lstm = nn.LSTM(
                input_dim, hidden_dim, num_layers=num_layers,
                dropout=dropout, batch_first=True,
            )
            self.fc = nn.Linear(hidden_dim, 1)
            self.sigmoid = nn.Sigmoid()

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            out, _ = self.lstm(x)
            out = self.fc(out[:, -1, :])
            return self.sigmoid(out).squeeze(-1)

    class _GRUNet(nn.Module):
        def __init__(self, input_dim: int, hidden_dim: int = 64, num_layers: int = 2, dropout: float = 0.2):
            super().__init__()
            self.gru = nn.GRU(
                input_dim, hidden_dim, num_layers=num_layers,
                dropout=dropout, batch_first=True,
            )
            self.fc = nn.Linear(hidden_dim, 1)
            self.sigmoid = nn.Sigmoid()

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            out, _ = self.gru(x)
            out = self.fc(out[:, -1, :])
            return self.sigmoid(out).squeeze(-1)


class LSTMModel(BaseModel):
    """LSTM-based direction classifier."""

    name = "lstm"

    def __init__(self, seq_len: int = 20, hidden_dim: int = 64, epochs: int = 50, lr: float = 1e-3):
        if not _TORCH_AVAILABLE:
            raise ImportError("PyTorch required for LSTM model")
        self.seq_len = seq_len
        self.hidden_dim = hidden_dim
        self.epochs = epochs
        self.lr = lr
        self.net: Any = None
        self._scaler: Any = None
        self._feature_names: list[str] = []

    def _prepare_sequences(self, X: pd.DataFrame, y: pd.Series | None = None):
        from sklearn.preprocessing import StandardScaler
        import torch

        if self._scaler is None:
            self._scaler = StandardScaler()
            X_scaled = self._scaler.fit_transform(X.fillna(0))
        else:
            X_scaled = self._scaler.transform(X.fillna(0))

        sequences = []
        targets = []
        for i in range(self.seq_len, len(X_scaled)):
            sequences.append(X_scaled[i - self.seq_len:i])
            if y is not None:
                targets.append(y.iloc[i])

        X_seq = torch.FloatTensor(np.array(sequences))
        y_seq = torch.FloatTensor(targets) if targets else None
        return X_seq, y_seq

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs: Any) -> dict:
        import torch
        import torch.nn as nn

        self._feature_names = list(X.columns)
        X_seq, y_seq = self._prepare_sequences(X, y)

        self.net = _LSTMNet(input_dim=X.shape[1], hidden_dim=self.hidden_dim)
        optimizer = torch.optim.Adam(self.net.parameters(), lr=self.lr)
        criterion = nn.BCELoss()

        self.net.train()
        for epoch in range(self.epochs):
            optimizer.zero_grad()
            preds = self.net(X_seq)
            loss = criterion(preds, y_seq)
            loss.backward()
            optimizer.step()
            if (epoch + 1) % 10 == 0:
                logger.debug("LSTM epoch %d/%d loss=%.4f", epoch + 1, self.epochs, loss.item())

        acc = ((preds > 0.5).float() == y_seq).float().mean().item()
        logger.info("LSTM fit: train_acc=%.4f", acc)
        return {"train_accuracy": acc}

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        proba = self.predict_proba(X)
        return (proba > 0.5).astype(int)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        import torch

        self.net.eval()
        X_seq, _ = self._prepare_sequences(X)
        with torch.no_grad():
            preds = self.net(X_seq).numpy()
        return preds


class GRUModel(LSTMModel):
    """GRU-based direction classifier (same interface as LSTM)."""

    name = "gru"

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs: Any) -> dict:
        import torch
        import torch.nn as nn

        self._feature_names = list(X.columns)
        X_seq, y_seq = self._prepare_sequences(X, y)

        self.net = _GRUNet(input_dim=X.shape[1], hidden_dim=self.hidden_dim)
        optimizer = torch.optim.Adam(self.net.parameters(), lr=self.lr)
        criterion = nn.BCELoss()

        self.net.train()
        for epoch in range(self.epochs):
            optimizer.zero_grad()
            preds = self.net(X_seq)
            loss = criterion(preds, y_seq)
            loss.backward()
            optimizer.step()

        acc = ((preds > 0.5).float() == y_seq).float().mean().item()
        logger.info("GRU fit: train_acc=%.4f", acc)
        return {"train_accuracy": acc}
