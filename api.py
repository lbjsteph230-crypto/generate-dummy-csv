import io
import json
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from app import download_csv, download_xlsx, generate_dataset, parse_name_repeat_prompt

app = FastAPI(title="Dummy Data Generator API", version="1.0.0")


ALLOWED_MODES = {"Static", "Randomize", "Custom Values"}
ALLOWED_FORMATS = {"csv", "xlsx"}


def _parse_json_field(raw: str | None, field_name: str, default: Any) -> Any:
    if raw is None or raw.strip() == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in '{field_name}': {exc}") from exc


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.post("/generate")
async def generate(
    file: UploadFile = File(...),
    n_rows: int = Form(100),
    allow_duplicate_names: bool = Form(True),
    name_rule_prompt: str = Form(""),
    output_format: str = Form("csv"),
    column_modes: str | None = Form(None),
    custom_values_map: str | None = Form(None),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are supported.")

    if n_rows < 1:
        raise HTTPException(status_code=400, detail="n_rows must be >= 1")

    output_format = output_format.lower().strip()
    if output_format not in ALLOWED_FORMATS:
        raise HTTPException(status_code=400, detail="output_format must be 'csv' or 'xlsx'")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded CSV is empty")

    try:
        template_df = pd.read_csv(io.BytesIO(content), encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Unable to decode CSV as UTF-8") from exc
    except pd.errors.EmptyDataError as exc:
        raise HTTPException(status_code=400, detail="Uploaded CSV has no data") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {exc}") from exc

    if template_df.columns.empty:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    modes_payload = _parse_json_field(column_modes, "column_modes", default={})
    custom_payload = _parse_json_field(custom_values_map, "custom_values_map", default={})

    if not isinstance(modes_payload, dict):
        raise HTTPException(status_code=400, detail="column_modes must be a JSON object")
    if not isinstance(custom_payload, dict):
        raise HTTPException(status_code=400, detail="custom_values_map must be a JSON object")

    # Defaults: Randomize all columns if client does not provide modes.
    resolved_modes: dict[str, str] = {col: "Randomize" for col in template_df.columns}
    for col, mode in modes_payload.items():
        if col not in template_df.columns:
            continue
        mode_value = str(mode).strip()
        if mode_value not in ALLOWED_MODES:
            raise HTTPException(status_code=400, detail=f"Invalid mode '{mode_value}' for column '{col}'")
        resolved_modes[col] = mode_value

    resolved_custom: dict[str, list[str]] = {}
    for col in template_df.columns:
        raw_values = custom_payload.get(col, [])
        if isinstance(raw_values, str):
            values = [v.strip() for v in raw_values.split(",") if v.strip()]
        elif isinstance(raw_values, list):
            values = [str(v).strip() for v in raw_values if str(v).strip()]
        else:
            values = []
        resolved_custom[col] = values

    same_name_count, force_unique_after_same = parse_name_repeat_prompt(name_rule_prompt)

    generated_df = generate_dataset(
        template_df=template_df,
        n_rows=int(n_rows),
        column_modes=resolved_modes,
        custom_values_map=resolved_custom,
        allow_duplicate_names=allow_duplicate_names,
        same_name_count=same_name_count,
        force_unique_after_same=force_unique_after_same,
    )

    if output_format == "xlsx":
        data = download_xlsx(generated_df)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "dummy_dataset_generated.xlsx"
    else:
        data = download_csv(generated_df)
        media_type = "text/csv"
        filename = "dummy_dataset_generated.csv"

    return StreamingResponse(
        io.BytesIO(data),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
