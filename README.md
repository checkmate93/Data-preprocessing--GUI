# DataPrep Studio

Web εφαρμογή (React + FastAPI + pandas, πάνω σε PocketFlow) για να ανεβάζεις οποιοδήποτε αρχείο δεδομένων
(CSV/TSV/TXT, Excel, JSON, JSONL, Parquet, Feather), να το επιθεωρείς και να το καθαρίζεις με 86 κουμπιά.
Κάθε βήμα κάνει νέα έκδοση (undo/redo) και γίνεται κώδικας pandas σε ένα `pipeline.py`. Επίσης: γραφήματα,
join με δεύτερο αρχείο, εφαρμογή αποθηκευμένου `recipe.json` σε νέο αρχείο, και ML Prep (train/test χωρίς leakage).

Design: [docs/design.md](docs/design.md) · Παλιό ML pipeline (v1): [docs/design_v1_ml_pipeline.md](docs/design_v1_ml_pipeline.md)

## Εκτέλεση

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
.venv\Scripts\python -m uvicorn app:app --port 8000
```

Άνοιξε http://localhost:8000. Για ανάπτυξη του frontend με hot reload: `uvicorn app:app --reload` και σε άλλο
τερματικό `cd frontend && npm run dev` (http://localhost:5173, το `/api` πάει στο :8000).

- Tests: `.venv\Scripts\python -m pytest tests`
- CLI demo χωρίς server: `.venv\Scripts\python main.py [αρχείο]`
- Ρυθμίσεις (env): `MAX_UPLOAD_MB` (200), `SESSION_TTL_HOURS` (24), `STORAGE_DIR` (`./storage`)

## Βοηθός (chat)

Κουμπί «💬 Βοηθός»: ερωτήσεις ή αλλαγές σε φυσική γλώσσα. Το μοντέλο τρέχει κουμπιά ή γράφει κώδικα
pandas/sklearn/statsmodels που εκτελείται σε απομονωμένη διεργασία. Κάθε αλλαγή = νέα έκδοση (αναίρεση) και μπαίνει
στο `pipeline.py`. «Καθαρισμός» σβήνει τη συνομιλία και μηδενίζει τα tokens (οι εκδόσεις των δεδομένων μένουν).

| Μεταβλητή | Τι κάνει |
|---|---|
| `ANTHROPIC_API_KEY` ή `OPENAI_API_KEY` | Ενεργοποιεί τον βοηθό (χωρίς κλειδί είναι απενεργοποιημένος) |
| `DATAPREP_LLM_PROVIDER`, `DATAPREP_LLM_MODEL`, `DATAPREP_LLM_BASE_URL` | Επιλογή provider/μοντέλου/gateway (default `claude-sonnet-5-5` / `gpt-4o`) |
| `DATAPREP_ASSISTANT_TOKEN` | Κωδικός πρόσβασης· **βάλ' τον σε δημόσιο deployment** για να μην καίει tokens οποιοσδήποτε |
| `DATAPREP_CHAT_MAX_PER_HOUR` (30), `DATAPREP_CHAT_MAX_STEPS` (6), `DATAPREP_CHAT_HISTORY_TURNS` (6) | Όρια κόστους |
| `DATAPREP_SANDBOX_TIMEOUT` (60 s), `DATAPREP_SANDBOX_MEMORY_MB` (2048, Linux) | Όρια εκτέλεσης κώδικα |

Στο μοντέλο στέλνονται ονόματα/τύποι στηλών, στατιστικά, έως 5 συχνές τιμές ανά στήλη κατηγοριών και τα
αποτελέσματα του κώδικα — όχι ολόκληρο το αρχείο. Για δεδομένα πελατών χρειάζεται έγκριση για τον provider.

## Νέο κουμπί σε 3 βήματα

1. Γράψε τη λογική ως καθαρή συνάρτηση στο `utils/ops/helpers.py` (επιστρέφει `(df, report)`).
2. Κάνε την εγγραφή με `@operation(...)` στο αντίστοιχο `utils/ops/*.py`: params (pydantic), `fn`, `code`.
3. Τέλος. Το React φτιάχνει μόνο του το κουμπί και τη φόρμα από το `GET /api/operations`.

Τα δεδομένα των sessions μένουν στη μνήμη και στο `storage/` και σβήνονται στο restart. Τα αρχεία πελατών
δεν φεύγουν ποτέ από τον server (δεν υπάρχει κλήση LLM στο MVP).

---

<h1 align="center">Pocket Flow Project Template: Agentic Coding</h1>

<p align="center">
  <a href="https://github.com/The-Pocket/PocketFlow" target="_blank">
    <img 
      src="./assets/banner.png" width="800"
    />
  </a>
</p>

This is a project template for Agentic Coding with [Pocket Flow](https://github.com/The-Pocket/PocketFlow), a 100-line LLM framework, and your editor of choice.

- We have included rules files for various AI coding assistants to help you build LLM projects:
  - [.cursorrules](.cursorrules) for Cursor AI
  - [.clinerules](.clinerules) for Cline
  - [.windsurfrules](.windsurfrules) for Windsurf
  - [.goosehints](.goosehints) for Goose
  - Configuration in [.github](.github) for GitHub Copilot
  - [CLAUDE.md](CLAUDE.md) for Claude Code
  - [GEMINI.md](GEMINI.md) for Gemini
  
- Want to learn how to build LLM projects with Agentic Coding?

  - Check out the [Agentic Coding Guidance](https://the-pocket.github.io/PocketFlow/guide.html)
    
  - Check out the [YouTube Tutorial](https://www.youtube.com/@ZacharyLLM?sub_confirmation=1)
