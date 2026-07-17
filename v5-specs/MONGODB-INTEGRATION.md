# Intégration MongoDB — V5

> **Objectif :** fournir une couche d'historisation locale et gratuite pour toutes les exécutions du pipeline de transcription.

---

## Pourquoi MongoDB ?

- **Local** : installation via Docker ou binaire natif Windows, pas de SaaS.
- **Gratuit** : licence SSPL, usage personnel/dev autorisé.
- **Schéma flexible** : chaque run génère des structures différentes (notes, warnings, métriques).
- **Requêtes temporelles** : idéal pour le suivi d'évolution des métriques.
- **Native async** : `motor` (async driver) compatible avec FastAPI.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  FastAPI (app.py)                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │ Pipeline    │  │ MongoDB     │  │ SSE Stream  │ │
│  │             │  │ Service     │  │             │ │
│  └─────────────┘  └─────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  MongoDB Local  │
              │  (27017)        │
              └─────────────────┘
```

---

## Collections

### 1. `runs` — Historique des exécutions

```javascript
{
  _id: ObjectId,
  run_id: "uuid-v4",               // Unique par exécution
  timestamp: ISODate,              // Date exécution
  file_name: "Mazurka.flac",       // Nom fichier source
  file_hash: "sha256:abc123",      // Hash pour détection doublons
  preset: "classique",             // Preset utilisé
  options: {                      // Options pipeline
    sensitivity: 0.85,
    quantization: "standard",
    split_stems: true,
    // ... toutes les options envoyées
  },
  status: "success" | "failed" | "partial",  // Statut exécution
  duration_seconds: 42.5,         // Durée exécution
  warnings: [                    // Warnings collectés
    {
      code: "TONALITY_DETECTOR_MISSING",
      message: "tonality_detector non disponible",
      severity: "warning",
      timestamp: ISODate
    }
  ],
  errors: [                      // Erreurs (si échec)
    {
      code: "DEMUCS_FAILED",
      message: "séparation échouée",
      severity: "error",
      traceback: "..."
    }
  ],
  metrics: {                     // Métriques qualité (Phase 7)
    f1_notes_mg: 0.92,
    f1_notes_md: 0.89,
    rhythm_accuracy: 0.95,
    ornaments_preserved: 0.87,
    // ...
  },
  artifacts: {                   // Chemins fichiers générés
    musicxml: "outputs/xxx.xml",
    pdf: "outputs/xxx.pdf",
    log: "outputs/xxx.log"
  }
}
```

### 2. `notes` — Notes détectées (détaillé)

```javascript
{
  _id: ObjectId,
  run_id: "uuid-v4",             // Lien vers runs
  hand: "left" | "right",        // Main
  onset_raw: 1.234,              // Onset brut (secondes)
  onset_quantized: 1.250,        // Onset quantifié
  offset_raw: 1.800,
  offset_quantized: 1.750,
  pitch: 69,                     // MIDI note
  velocity: 85,                  // 0-127
  confidence: 0.92,              // Confiance détection
  uncertain: false               // Flag note incertaine
}
```

### 3. `tempo_maps` — Cartes tempo

```javascript
{
  _id: ObjectId,
  run_id: "uuid-v4",
  detected_tempo: 96.5,          // Tempo détecté
  signature: "3/4",             // Signature détectée
  beats: [                      // Points tempo
    {
      time: 0.0,
      bpm: 96.5,
      beat: 0,
      is_downbeat: true
    }
  ]
}
```

### 4. `migrations` — Historisation schéma

```javascript
{
  _id: ObjectId,
  version: "5.0.0",
  applied_at: ISODate,
  description: "init v5 schema"
}
```

---

## Intégration code

### Structure

```
backend/
├── services/
│   └── mongodb_service.py      # Client + CRUD
├── models/
│   └── run_model.py            # Pydantic models
└── app.py                      # Injection dépendances
```

### `mongodb_service.py`

```python
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
import logging

logger = logging.getLogger(__name__)

class MongoDBService:
    """Service MongoDB avec fallback gracieux."""
    
    def __init__(self, uri: str = "mongodb://localhost:27017", 
                 db_name: str = "audio_to_sheet_v5"):
        self.uri = uri
        self.db_name = db_name
        self.client = None
        self.db = None
        self.available = False
    
    async def connect(self):
        """Connexion avec fallback gracieux."""
        try:
            self.client = AsyncIOMotorClient(
                self.uri, 
                serverSelectionTimeoutMS=3000
            )
            self.db = self.client[self.db_name]
            # Test connexion
            await self.db.command("ping")
            self.available = True
            logger.info("✅ MongoDB connecté")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(f"⚠️ MongoDB indisponible: {e}")
            logger.warning("   Pipeline continuera sans historisation")
            self.available = False
    
    async def save_run(self, run_data: dict) -> str | None:
        """Sauvegarde une exécution. Retourne run_id ou None si MongoDB down."""
        if not self.available:
            return None
        try:
            result = await self.db.runs.insert_one(run_data)
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde run: {e}")
            return None
    
    async def get_run(self, run_id: str) -> dict | None:
        """Récupère un run par ID."""
        if not self.available:
            return None
        return await self.db.runs.find_one({"run_id": run_id})
    
    async def get_runs_by_file(self, file_name: str, limit: int = 10):
        """Historique runs pour un fichier."""
        if not self.available:
            return []
        cursor = self.db.runs.find({"file_name": file_name})
        cursor = cursor.sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)
    
    async def get_metrics_evolution(self, file_hash: str):
        """Évolution métriques pour un fichier (graphes)."""
        if not self.available:
            return []
        pipeline = [
            {"$match": {"file_hash": file_hash, "metrics": {"$exists": True}}},
            {"$project": {
                "timestamp": 1,
                "metrics": 1,
                "preset": 1,
                "options": 1
            }}
        ]
        return await self.db.runs.aggregate(pipeline).to_list(length=100)
```

### `run_model.py` (Pydantic)

```python
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import uuid4

class RunOptions(BaseModel):
    sensitivity: float = 0.85
    quantization: str = "standard"
    preset: str = "classique"
    split_stems: bool = True
    # ... autres options

class Warning(BaseModel):
    code: str
    message: str
    severity: str = "warning"
    timestamp: datetime = Field(default_factory=datetime.now)

class RunData(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)
    file_name: str
    file_hash: str
    preset: str
    options: RunOptions
    status: str = "running"
    duration_seconds: Optional[float] = None
    warnings: list[Warning] = []
    errors: list[dict] = []
    metrics: Optional[dict] = None
    artifacts: Optional[dict] = None
```

---

## Docker Compose

Ajout au `docker-compose.yml` existant :

```yaml
services:
  # ... services existants
  
  mongodb:
    image: mongo:7
    container_name: audio-to-sheet-mongo
    ports:
      - "27017:27017"
    volumes:
      - mongodb_data:/data/db
    environment:
      MONGO_INITDB_DATABASE: audio_to_sheet_v5

volumes:
  mongodb_data:
```

---

## Progression intégration

| Phase | Intégration MongoDB | Détails |
|-------|---------------------|---------|
| Phase 1 | `mongodb_service.py` + connexion | Base infrastructure |
| Phase 1 | Sauvegarde runs (basique) | file_name, options, status, warnings |
| Phase 3 | `tempo_maps` collection | Stockage cartes tempo |
| Phase 5 | `notes` collection (optionnel) | Si besoin debug détaillé |
| Phase 7 | Métriques + requêtes évolution | Comparaison runs, graphes |
| Phase 7 | Frontend : historique runs | UI consultation historique |

---

## Règles d'or

1. **MongoDB est optionnel au runtime** : le pipeline fonctionne SANS MongoDB (fallback gracieux).
2. **Tout échec MongoDB est loggé, jamais fatal** : `warnings.append()` puis continuation.
3. **Aucune donnée sensible stockée** : pas de contenu audio en base, seulement les métadonnées.
4. **Index obligatoires** : `run_id`, `file_hash`, `timestamp` pour les performances.
5. **Rotation automatique** : garder uniquement les 100 derniers runs par fichier.

---

## Indexs MongoDB

```python
async def create_indexes(self):
    if not self.available:
        return
    await self.db.runs.create_index("run_id")
    await self.db.runs.create_index("file_hash")
    await self.db.runs.create_index("timestamp")
    await self.db.runs.create_index([("file_name", 1), ("timestamp", -1)])
    await self.db.notes.create_index("run_id")
    await self.db.tempo_maps.create_index("run_id")
```

---

## API FastAPI — Endpoints historiques

```python
# GET /api/runs?file_name=Mazurka.flac&limit=10
# GET /api/runs/{run_id}
# GET /api/runs/{run_id}/metrics-evolution
# GET /api/runs/{run_id}/notes
# DELETE /api/runs/{run_id}  (nettoyage)