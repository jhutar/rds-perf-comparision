#!/usr/bin/env python3
"""
Recursively collect vu_*.json benchmark result files under an archive tree,
flatten EC2/RDS CloudWatch-style metrics and NOPM/TPM into one Excel workbook.

Dependency:
    pip install openpyxl

Example:
    python export_archive_vu_metrics_to_excel.py \\
        --archive ../results/archive

    Default output: archive_vu_metrics_summary.xlsx in this scripts/ directory.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from openpyxl import Workbook

# Parent folder: .../rds-perf-dbm7ixlarge-vu8-run3-2026-03-23T15_11_10_...
PARENT_RUN_RE = re.compile(
    r"rds-perf-(?P<matrix>.+)-vu(?P<vu>\d+)-run(?P<iteration>\d+)-",
    re.IGNORECASE,
)
# File: vu_8_wh_512_db_m7i_xlarge_m7i_12xlarge_2026-03-23T15_11_10_980775588_05_30.json
VU_FILE_RE = re.compile(
    r"^vu_(?P<vu>\d+)_wh_(?P<wh>\d+)_db_(?P<rest>.+)_(?P<stamp>\d{4}-\d{2}-\d{2}T.+)\.json$",
    re.IGNORECASE,
)
LOAD_GEN_SUFFIX = "_m7i_12xlarge"

# Columns written to the workbook (order preserved). All other keys from JSON are dropped.
EXPORT_COLUMNS: list[str] = [
    "Test_Iteration",
    "RDS_Instance_Type",
    "Virtual_Users",
    "Warehouse_Count",
    "NOPM",
    "TPM",
    "EC2_CPU_Utilization_Average",
    "EC2_CPU_Utilization_Maximum",
    "EC2_Network_In_Average",
    "EC2_Network_In_Maximum",
    "EC2_Network_In_Sum",
    "EC2_Network_Out_Average",
    "EC2_Network_Out_Maximum",
    "EC2_Network_Out_Sum",
    "EC2_Network_Packets_In_Average",
    "EC2_Network_Packets_In_Maximum",
    "EC2_Network_Packets_In_Sum",
    "EC2_Network_Packets_Out_Average",
    "EC2_Network_Packets_Out_Maximum",
    "EC2_Network_Packets_Out_Sum",
    "RDS_CPU_Utilization_Average",
    "RDS_CPU_Utilization_Maximum",
    "RDS_Checkpoint_Lag_Average",
    "RDS_Checkpoint_Lag_Maximum",
    "RDS_DB_Load_Average",
    "RDS_DB_Load_CPU_Average",
    "RDS_DB_Load_CPU_Maximum",
    "RDS_DB_Load_Maximum",
    "RDS_DB_Load_Non_CPU_Average",
    "RDS_DB_Load_Non_CPU_Maximum",
    "RDS_DB_Load_Relative_To_Num_VCP_Us_Average",
    "RDS_DB_Load_Relative_To_Num_VCP_Us_Maximum",
    "RDS_Database_Connections_Average",
    "RDS_Database_Connections_Maximum",
    "RDS_Disk_Queue_Depth_Average",
    "RDS_Disk_Queue_Depth_Maximum",
    "RDS_EBSIO_Balance_Pct_Average",
    "RDS_EBS_Byte_Balance_Pct_Average",
    "RDS_Free_Storage_Space_Average",
    "RDS_Free_Storage_Space_Minimum",
    "RDS_Freeable_Memory_Average",
    "RDS_Freeable_Memory_Minimum",
    "RDS_Maximum_Used_Transaction_I_Ds_Maximum",
    "RDS_Network_Receive_Throughput_Average",
    "RDS_Network_Receive_Throughput_Maximum",
    "RDS_Network_Transmit_Throughput_Average",
    "RDS_Network_Transmit_Throughput_Maximum",
    "RDS_Oldest_Logical_Replication_Slot_Lag_Maximum",
    "RDS_Oldest_Replication_Slot_Lag_Maximum",
    "RDS_Read_IOPS_Average",
    "RDS_Read_IOPS_Maximum",
    "RDS_Read_Latency_Average",
    "RDS_Read_Latency_Maximum",
    "RDS_Read_Throughput_Average",
    "RDS_Read_Throughput_Maximum",
    "RDS_Replication_Slot_Disk_Usage_Average",
    "RDS_Replication_Slot_Disk_Usage_Maximum",
    "RDS_Swap_Usage_Average",
    "RDS_Swap_Usage_Maximum",
    "RDS_Transaction_Logs_Disk_Usage_Average",
    "RDS_Transaction_Logs_Disk_Usage_Maximum",
    "RDS_Transaction_Logs_Generation_Average",
    "RDS_Transaction_Logs_Generation_Maximum",
    "RDS_Write_IOPS_Average",
    "RDS_Write_IOPS_Maximum",
    "RDS_Write_Latency_Average",
    "RDS_Write_Latency_Maximum",
    "RDS_Write_Throughput_Average",
    "RDS_Write_Throughput_Maximum",
]


def _camel_to_snake(name: str) -> str:
    """Turn CloudWatch PascalCase names into snake fragments for column titles."""
    n = name.replace("%", "Pct").replace("/", "_per_")
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", n)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return re.sub(r"[^a-zA-Z0-9_]+", "_", s2).strip("_")


def _excel_safe_header(s: str) -> str:
    return re.sub(r"[\[\]*?:/\\]", "_", s)


def _parse_vu_filename(stem: str) -> dict[str, Any]:
    """Parse vu_* filename into virtual users, warehouses, instance class strings."""
    m = VU_FILE_RE.match(stem + ".json")
    out: dict[str, Any] = {
        "virtual_users_from_filename": None,
        "warehouse_count_from_filename": None,
        "rds_instance_class_slug": None,
        "load_generator_instance_slug": None,
        "result_file_perf_stamp": None,
    }
    if not m:
        return out
    vu, wh, rest, stamp = m.group("vu", "wh", "rest", "stamp")
    out["virtual_users_from_filename"] = int(vu)
    out["warehouse_count_from_filename"] = int(wh)
    out["result_file_perf_stamp"] = stamp
    slug = rest
    if slug.lower().endswith(LOAD_GEN_SUFFIX):
        db_part = slug[: -len(LOAD_GEN_SUFFIX)]
        out["rds_instance_class_slug"] = db_part
        out["load_generator_instance_slug"] = "m7i_12xlarge"
    else:
        out["rds_instance_class_slug"] = slug
    return out


def _slug_to_instance_type(slug: str | None) -> str | None:
    if not slug:
        return None
    parts = slug.split("_")
    if len(parts) < 2:
        return slug.replace("_", ".")
    family, size, *extra = parts[0], parts[1], parts[2:]
    base = f"{family}.{size}"
    if extra:
        return base + "." + ".".join(extra)
    return base


def _parse_parent_run(folder_name: str) -> dict[str, Any]:
    m = PARENT_RUN_RE.search(folder_name)
    if not m:
        return {
            "matrix_label": None,
            "virtual_users_from_folder": None,
            "test_iteration": None,
        }
    return {
        "matrix_label": m.group("matrix"),
        "virtual_users_from_folder": int(m.group("vu")),
        "test_iteration": int(m.group("iteration")),
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _find_run_metadata(vu_json_path: Path) -> dict[str, Any] | None:
    d = vu_json_path.parent
    for p in sorted(d.glob("run-metadata*.json")):
        loaded = _load_json(p)
        if loaded:
            return loaded
    return None


def _flatten_cloudwatch_block(
    block: dict[str, Any] | None, source_label: str
) -> dict[str, Any]:
    """source_label: 'EC2' or 'RDS' -> keys like EC2_CPU_Utilization_Average."""
    flat: dict[str, Any] = {}
    if not isinstance(block, dict):
        return flat
    for metric_name, payload in block.items():
        if not isinstance(payload, dict):
            continue
        metric_snake = _camel_to_snake(metric_name)
        for stat, val in payload.items():
            if stat == "Unit":
                continue
            col = _excel_safe_header(f"{source_label}_{metric_snake}_{stat}")
            flat[col] = val
    return flat


def _maybe_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(str(v).strip())
    except ValueError:
        try:
            return int(float(str(v).strip()))
        except ValueError:
            return None


def _row_from_vu_json(
    vu_path: Path, archive_root: Path
) -> dict[str, Any] | None:
    data = _load_json(vu_path)
    if data is None:
        return None

    rel = vu_path.relative_to(archive_root)
    parent_info = _parse_parent_run(vu_path.parent.name)
    fname_info = _parse_vu_filename(vu_path.stem)
    meta = _find_run_metadata(vu_path)

    row: dict[str, Any] = {
        "Source_Relative_Path": str(rel).replace("\\", "/"),
        "Archive_Folder_Name": vu_path.parent.name,
        "Matrix_Label": parent_info["matrix_label"],
        "Test_Iteration": parent_info["test_iteration"],
        "Virtual_Users": None,
        "Warehouse_Count": None,
        "RDS_Instance_Type": None,
        "Load_Generator_EC2_Instance_Type": None,
        "AWS_Region": None,
        "Perf_Run_Stamp": None,
        "NOPM": None,
        "TPM": None,
    }

    if meta:
        row["Virtual_Users"] = _maybe_int(meta.get("virtual_users"))
        row["Warehouse_Count"] = _maybe_int(meta.get("warehouse_count"))
        row["RDS_Instance_Type"] = meta.get("aws_rds_instance_type")
        row["Load_Generator_EC2_Instance_Type"] = meta.get("aws_ec2_instance_type")
        row["AWS_Region"] = meta.get("aws_region")
        row["Perf_Run_Stamp"] = meta.get("perf_run_stamp")
        if meta.get("nopm") is not None:
            row["NOPM"] = _maybe_int(meta.get("nopm"))
        if meta.get("tpm") is not None:
            row["TPM"] = _maybe_int(meta.get("tpm"))

    if row["Virtual_Users"] is None:
        row["Virtual_Users"] = fname_info.get("virtual_users_from_filename")
    if row["Warehouse_Count"] is None:
        row["Warehouse_Count"] = fname_info.get("warehouse_count_from_filename")
    if row["RDS_Instance_Type"] is None:
        row["RDS_Instance_Type"] = _slug_to_instance_type(
            fname_info.get("rds_instance_class_slug")
        )
    if row["Load_Generator_EC2_Instance_Type"] is None:
        row["Load_Generator_EC2_Instance_Type"] = _slug_to_instance_type(
            fname_info.get("load_generator_instance_slug")
        )
    if row["Perf_Run_Stamp"] is None:
        row["Perf_Run_Stamp"] = fname_info.get("result_file_perf_stamp")

    if row["NOPM"] is None and data.get("nopm") is not None:
        row["NOPM"] = _maybe_int(data.get("nopm"))
    if row["TPM"] is None and data.get("tpm") is not None:
        row["TPM"] = _maybe_int(data.get("tpm"))

    row.update(_flatten_cloudwatch_block(data.get("ec2_cloudwatch"), "EC2"))
    row.update(_flatten_cloudwatch_block(data.get("rds_cloudwatch"), "RDS"))
    return row


def _write_xlsx(path: Path, sheet_name: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]
    ws.append(columns)
    for r in rows:
        ws.append([r.get(c) for c in columns])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Flatten vu_*.json metrics under archive/ into one Excel workbook."
    )
    ap.add_argument(
        "--archive",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "results" / "archive",
        help="Root directory to search",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "archive_vu_metrics_summary.xlsx",
        help="Output .xlsx path (default: scripts/archive_vu_metrics_summary.xlsx)",
    )
    ap.add_argument(
        "--sheet",
        default="RDS_Perf_Metrics",
        help="Worksheet name (max 31 characters)",
    )
    args = ap.parse_args()

    archive_root = args.archive.resolve()
    if not archive_root.is_dir():
        raise SystemExit(f"Archive path is not a directory: {archive_root}")

    vu_files = sorted(archive_root.rglob("vu_*.json"))
    if not vu_files:
        raise SystemExit(f"No vu_*.json files under {archive_root}")

    rows: list[dict[str, Any]] = []
    for p in vu_files:
        r = _row_from_vu_json(p, archive_root)
        if r:
            rows.append(r)

    if not rows:
        raise SystemExit("No valid JSON rows produced.")

    columns = EXPORT_COLUMNS

    _write_xlsx(args.output.resolve(), args.sheet, columns, rows)
    print(
        f"Wrote {len(rows)} rows × {len(columns)} columns -> {args.output.resolve()}"
    )


if __name__ == "__main__":
    main()
