import io
import random
import re
from datetime import date, timedelta

import pandas as pd
import streamlit as st


FILIPINO_FIRST_NAMES = [
    "Juan",
    "Mark",
    "Carlo",
    "Miguel",
    "Paolo",
    "Joshua",
    "Rafael",
    "Luis",
    "Angelo",
    "Patrick",
    "Jomar",
    "Renato",
    "Daniel",
    "Jerome",
    "Adrian",
]

FILIPINO_FEMALE_FIRST_NAMES = [
    "Maria",
    "Angela",
    "Sofia",
    "Patricia",
    "Camille",
    "Jasmine",
    "Bianca",
    "Andrea",
    "Nicole",
    "Elaine",
    "Rica",
    "Katrina",
    "Alyssa",
    "Trisha",
    "Bea",
]
FEMALE_FIRST_NAMES_LOWER = {name.lower() for name in FILIPINO_FEMALE_FIRST_NAMES}

FILIPINO_LAST_NAMES = [
    "Santos",
    "Reyes",
    "Cruz",
    "Garcia",
    "Torres",
    "Flores",
    "Bautista",
    "Domingo",
    "Castro",
    "Ramos",
    "Navarro",
    "Aquino",
    "Valdez",
    "Del Rosario",
]

NAME_KEYWORDS = ["name", "customer", "client", "borrower"]
CODE_KEYWORDS = ["code", "score", "ch"]
AMOUNT_KEYWORDS = ["amount", "balance", "limit", "loan"]
GENDER_KEYWORDS = ["gender", "sex"]


class GenerationContext:
    def __init__(self) -> None:
        self.used_names = set()
        self.used_account_numbers = set()
        self.same_name_per_column: dict[str, str] = {}
        self.current_row_gender: str | None = None


def load_csv(uploaded_file) -> pd.DataFrame | None:
    """Load CSV safely and return dataframe or None on failure."""
    if uploaded_file is None:
        return None

    if not uploaded_file.name.lower().endswith(".csv"):
        st.warning("Unsupported format. Please upload a .csv file.")
        return None

    try:
        df = pd.read_csv(uploaded_file, encoding="utf-8")
    except UnicodeDecodeError:
        st.warning("Unable to decode file as UTF-8. Please save your CSV with UTF-8 encoding.")
        return None
    except pd.errors.EmptyDataError:
        st.warning("The uploaded CSV is empty.")
        return None
    except Exception as exc:
        st.warning(f"Failed to read CSV: {exc}")
        return None

    if df.columns.empty:
        st.warning("CSV has no headers.")
        return None

    return df


def parse_date_sample(value) -> bool:
    """Return True if sample value looks like a date."""
    if pd.isna(value):
        return False

    text = str(value).strip()
    if not text:
        return False

    parsed = pd.to_datetime(text, errors="coerce")
    return pd.notna(parsed)


def detect_column_type(column_name: str, sample_value) -> str:
    """Detect generation strategy from column name and sample value."""
    col_lower = column_name.lower()

    if any(keyword in col_lower for keyword in NAME_KEYWORDS):
        return "name"

    if any(keyword in col_lower for keyword in AMOUNT_KEYWORDS):
        return "amount"

    if any(keyword in col_lower for keyword in CODE_KEYWORDS):
        return "code"

    if parse_date_sample(sample_value):
        return "date"

    if pd.notna(sample_value):
        sample_text = str(sample_value).strip()

        if re.fullmatch(r"09\d{9}", sample_text):
            return "phone"

        if sample_text.isdigit() and len(sample_text) >= 8:
            return "account_number"

        if sample_text.isdigit():
            return "numeric"

    return "text"


def generate_unique_account_number(ctx: GenerationContext, length: int = 10) -> str:
    max_attempts = 2000
    lower = 10 ** (length - 1)
    upper = (10**length) - 1

    for _ in range(max_attempts):
        candidate = str(random.randint(lower, upper))
        if candidate not in ctx.used_account_numbers:
            ctx.used_account_numbers.add(candidate)
            return candidate

    # Fallback
    return str(random.randint(lower, upper))


def random_date_between(start_year: int = 1970, end_year: int = 2005) -> str:
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    delta_days = (end - start).days
    d = start + timedelta(days=random.randint(0, delta_days))
    return d.isoformat()


def parse_name_repeat_prompt(prompt: str) -> tuple[int, bool]:
    """
    Parse prompt-style instruction like:
    'generate 10 same names and the rest are unique'
    """
    if not prompt or not prompt.strip():
        return 0, False

    prompt_lower = prompt.lower()
    number_match = re.search(r"\b(\d+)\b", prompt_lower)
    if not number_match:
        return 0, False

    has_name_keyword = "name" in prompt_lower
    has_repeat_intent = any(word in prompt_lower for word in ["same", "repeat", "duplicate"])
    has_rest_unique = "rest" in prompt_lower and "unique" in prompt_lower
    if has_name_keyword and has_repeat_intent:
        return max(0, int(number_match.group(1))), has_rest_unique

    return 0, False


def generate_name_with_gender(
    ctx: GenerationContext,
    force_gender: str | None = None,
    allow_duplicates: bool = True,
) -> tuple[str, str]:
    max_attempts = 3000

    male_pool = FILIPINO_FIRST_NAMES
    female_pool = FILIPINO_FEMALE_FIRST_NAMES

    for _ in range(max_attempts):
        if force_gender == "male":
            first = random.choice(male_pool)
            gender = "male"
        elif force_gender == "female":
            first = random.choice(female_pool)
            gender = "female"
        else:
            if random.random() < 0.5:
                first = random.choice(male_pool)
                gender = "male"
            else:
                first = random.choice(female_pool)
                gender = "female"

        candidate = f"{first} {random.choice(FILIPINO_LAST_NAMES)}"
        if allow_duplicates or candidate not in ctx.used_names:
            ctx.used_names.add(candidate)
            return candidate, gender

    suffix = random.randint(100, 999)
    candidate = f"{random.choice(male_pool + female_pool)} {random.choice(FILIPINO_LAST_NAMES)} {suffix}"
    ctx.used_names.add(candidate)
    return candidate, "male"


def generate_name_with_repeat_rule(
    ctx: GenerationContext,
    column_name: str,
    row_index: int,
    allow_duplicate_names: bool,
    same_name_count: int,
    force_unique_after_same: bool,
) -> str:
    """Use one same name for first N rows; then unique names if configured."""
    if same_name_count > 0 and row_index < same_name_count:
        shared_name = ctx.same_name_per_column.get(column_name)
        if shared_name is None:
            shared_name, gender = generate_name_with_gender(ctx, allow_duplicates=True)
            ctx.same_name_per_column[column_name] = shared_name
            ctx.current_row_gender = gender
            return shared_name

        first_name = shared_name.split(" ")[0].lower()
        if first_name in FEMALE_FIRST_NAMES_LOWER:
            ctx.current_row_gender = "female"
        else:
            ctx.current_row_gender = "male"
        return shared_name

    name, gender = generate_name_with_gender(
        ctx=ctx,
        allow_duplicates=(allow_duplicate_names and not force_unique_after_same),
    )
    ctx.current_row_gender = gender
    return name


def format_gender_value(target_gender: str, sample_values: list[str]) -> str:
    """
    Match generated gender to template format when possible.
    Examples: Male/Female, M/F.
    """
    normalized = []
    for value in sample_values:
        text = str(value).strip()
        if text:
            normalized.append(text)

    lower_set = {v.lower() for v in normalized}

    if {"male", "female"}.issubset(lower_set):
        return "Male" if target_gender == "male" else "Female"
    if {"m", "f"}.issubset(lower_set):
        return "M" if target_gender == "male" else "F"

    # Fallback to common format
    return "Male" if target_gender == "male" else "Female"


def generate_value(
    mode: str,
    column_name: str,
    sample_value,
    sample_values: list,
    custom_values: list[str],
    row_index: int,
    allow_duplicate_names: bool,
    same_name_count: int,
    force_unique_after_same: bool,
    ctx: GenerationContext,
):
    """Generate value for a column based on selected mode and heuristics."""
    if mode == "Static":
        return sample_value

    if mode == "Custom Values":
        if custom_values:
            return random.choice(custom_values)
        return sample_value

    col_lower = column_name.lower()
    if any(k in col_lower for k in GENDER_KEYWORDS):
        if ctx.current_row_gender in {"male", "female"}:
            return format_gender_value(ctx.current_row_gender, [str(v) for v in sample_values])
        # No corresponding name in row; fallback random gender preserving known format.
        random_gender = random.choice(["male", "female"])
        return format_gender_value(random_gender, [str(v) for v in sample_values])

    col_type = detect_column_type(column_name, sample_value)

    if col_type == "name":
        return generate_name_with_repeat_rule(
            ctx=ctx,
            column_name=column_name,
            row_index=row_index,
            allow_duplicate_names=allow_duplicate_names,
            same_name_count=same_name_count,
            force_unique_after_same=force_unique_after_same,
        )

    if col_type == "account_number":
        sample_len = len(str(sample_value)) if pd.notna(sample_value) else 10
        sample_len = max(sample_len, 8)
        return generate_unique_account_number(ctx, sample_len)

    if col_type == "code":
        return f"CH{random.randint(100, 999)}"

    if col_type == "phone":
        return f"09{random.randint(100000000, 999999999)}"

    if col_type == "date":
        return random_date_between(1970, 2005)

    if col_type == "amount":
        return random.randint(1000, 200000)

    if col_type == "numeric":
        return random.randint(1, 99999)

    # Text fallback aligned with uploaded template: sample existing values first.
    existing_text_values = [str(v) for v in sample_values if pd.notna(v) and str(v).strip() != ""]
    if existing_text_values:
        return random.choice(existing_text_values)

    return f"Sample-{random.randint(1000, 9999)}"


def generate_dataset(
    template_df: pd.DataFrame,
    n_rows: int,
    column_modes: dict[str, str],
    custom_values_map: dict[str, list[str]],
    allow_duplicate_names: bool,
    same_name_count: int,
    force_unique_after_same: bool,
) -> pd.DataFrame:
    """Generate dataset based on template and per-column modes."""
    ctx = GenerationContext()
    columns = list(template_df.columns)

    if len(template_df) == 0:
        sample_row = {col: "" for col in columns}
    else:
        sample_row = template_df.iloc[0].to_dict()
    sample_values_map = {
        col: template_df[col].dropna().tolist() if col in template_df.columns else []
        for col in columns
    }

    records = []
    for row_index in range(n_rows):
        ctx.current_row_gender = None
        row_data = {}
        for col in columns:
            mode = column_modes.get(col, "Static")
            custom_values = custom_values_map.get(col, [])
            sample_value = sample_row.get(col, "")
            sample_values = sample_values_map.get(col, [])
            value = generate_value(
                mode=mode,
                column_name=col,
                sample_value=sample_value,
                sample_values=sample_values,
                custom_values=custom_values,
                row_index=row_index,
                allow_duplicate_names=allow_duplicate_names,
                same_name_count=same_name_count,
                force_unique_after_same=force_unique_after_same,
                ctx=ctx,
            )

            # Preserve blanks when template sample was blank and mode is static
            if mode == "Static" and pd.isna(sample_value):
                value = ""

            row_data[col] = value
        records.append(row_data)

    return pd.DataFrame(records, columns=columns)


def download_csv(df: pd.DataFrame) -> bytes:
    """Convert dataframe to CSV bytes."""
    return df.to_csv(index=False).encode("utf-8")


def download_xlsx(df: pd.DataFrame) -> bytes:
    """Convert dataframe to XLSX bytes."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="DummyData")
    output.seek(0)
    return output.getvalue()


def build_column_config_template(template_df: pd.DataFrame) -> pd.DataFrame:
    """Build compact column configuration rows for the UI editor."""
    sample_row = template_df.iloc[0].to_dict() if len(template_df) > 0 else {c: "" for c in template_df.columns}
    rows = []
    for col in template_df.columns:
        sample_value = sample_row.get(col, "")
        display_sample = "" if pd.isna(sample_value) else str(sample_value)
        rows.append(
            {
                "Column": col,
                "Sample": display_sample,
                "Mode": "Randomize",
                "Custom Values": "",
            }
        )
    return pd.DataFrame(rows, columns=["Column", "Sample", "Mode", "Custom Values"])


def parse_custom_values_text(value: str) -> list[str]:
    if value is None:
        return []
    return [v.strip() for v in str(value).split(",") if v.strip()]


def main() -> None:
    st.set_page_config(page_title="CSV Dummy Data Generator", layout="wide")
    st.title("CSV Dummy Data Generator")

    st.subheader("Section 1 - Upload Template")
    uploaded_file = st.file_uploader("Upload CSV Template", type=["csv"])

    template_df = load_csv(uploaded_file)
    if template_df is None:
        return

    if template_df.shape[1] == 0:
        st.warning("CSV has no columns.")
        return

    st.write("Template Preview")
    st.dataframe(template_df.head(20), use_container_width=True)

    if template_df.shape[0] == 0:
        st.warning("CSV contains only headers. Static values will default to empty strings.")

    st.subheader("Section 2 - Generation Settings")
    n_rows = st.number_input(
        "Number of rows to generate",
        min_value=1,
        max_value=1_000_000,
        value=100,
        step=1,
    )

    allow_duplicate_names = st.checkbox("Allow duplicate names", value=True)
    name_repeat_prompt = st.text_input(
        "Optional name rule prompt",
        value="",
        placeholder="e.g. generate 10 same names and the rest are unique",
        help="Applies to randomized name columns.",
    )
    same_name_count, force_unique_after_same = parse_name_repeat_prompt(name_repeat_prompt)
    if name_repeat_prompt.strip() and same_name_count > 0:
        if force_unique_after_same:
            st.info(
                f"Name rule active: first {same_name_count} rows share the same name; remaining rows are unique."
            )
        else:
            st.info(f"Name rule active: first {same_name_count} rows share the same name.")
    elif name_repeat_prompt.strip():
        st.warning("Could not parse a valid name rule. Using normal name randomization.")

    st.subheader("Section 3 - Column Configuration")
    st.caption("Set modes directly in the table below.")

    column_modes: dict[str, str] = {}
    custom_values_map: dict[str, list[str]] = {}

    config_df = build_column_config_template(template_df)
    edited_config_df = st.data_editor(
        config_df,
        key="column_config_editor",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Column": st.column_config.TextColumn("Column", help="Column name from template"),
            "Sample": st.column_config.TextColumn("Sample", help="First sample value from template"),
            "Mode": st.column_config.SelectboxColumn(
                "Mode",
                options=["Static", "Randomize", "Custom Values"],
                required=True,
                default="Randomize",
            ),
            "Custom Values": st.column_config.TextColumn(
                "Custom Values",
                help="Comma-separated values. Used only when Mode is Custom Values.",
            ),
        },
        disabled=["Column", "Sample"],
    )

    missing_custom_columns: list[str] = []
    for row in edited_config_df.to_dict("records"):
        col = str(row.get("Column", "")).strip()
        if not col:
            continue
        mode = str(row.get("Mode", "Randomize")).strip()
        if mode not in {"Static", "Randomize", "Custom Values"}:
            mode = "Randomize"

        column_modes[col] = mode

        custom_text = row.get("Custom Values", "")
        values = parse_custom_values_text(custom_text)
        custom_values_map[col] = values
        if mode == "Custom Values" and not values:
            missing_custom_columns.append(col)

    if missing_custom_columns:
        st.warning(
            "Custom Values mode selected without values for: "
            + ", ".join(missing_custom_columns)
            + ". Sample value will be used."
        )

    st.subheader("Section 4 - Generate Data")
    generate_clicked = st.button("Generate Dummy Data", type="primary")

    if not generate_clicked:
        return

    with st.spinner("Generating dummy dataset..."):
        generated_df = generate_dataset(
            template_df=template_df,
            n_rows=int(n_rows),
            column_modes=column_modes,
            custom_values_map=custom_values_map,
            allow_duplicate_names=allow_duplicate_names,
            same_name_count=same_name_count,
            force_unique_after_same=force_unique_after_same,
        )

    st.success(f"Generated {len(generated_df):,} rows successfully.")
    st.dataframe(generated_df.head(50), use_container_width=True)

    st.subheader("Section 5 - Download")
    csv_bytes = download_csv(generated_df)

    st.download_button(
        label="Download CSV",
        data=csv_bytes,
        file_name="dummy_dataset_generated.csv",
        mime="text/csv",
    )

    if st.checkbox("Export as XLSX", value=False):
        try:
            xlsx_bytes = download_xlsx(generated_df)
            st.download_button(
                label="Download XLSX",
                data=xlsx_bytes,
                file_name="dummy_dataset_generated.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as exc:
            st.warning(f"XLSX export unavailable: {exc}")


if __name__ == "__main__":
    main()
