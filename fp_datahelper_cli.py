"""Run FP-DataHelper methods from a terminal."""

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
if sys.flags.isolated:
    sys.path.insert(0, str(ROOT))

from method_support import CANCEL_PATH_ENV, OUTPUT_DIR_ENV, RESULT_PATH_ENV
from skill_updates import check_update


FORMULAS = {"linear": "L", "kovats": "K", "both": "B"}
AGGREGATES = {"mean": "A", "min": "MIN", "max": "MAX"}

# Older Windows Python can fail to initialize MIME types in a restricted terminal.
WINDOWS_METHOD_BOOTSTRAP = """\
import mimetypes
import runpy
import sys

try:
    mimetypes.init()
except PermissionError:
    read_registry = mimetypes.MimeTypes.read_windows_registry
    try:
        mimetypes.MimeTypes.read_windows_registry = lambda self: None
        mimetypes.init(files=[])
    finally:
        mimetypes.MimeTypes.read_windows_registry = read_registry

sys.argv.pop(0)
runpy.run_path(sys.argv[0], run_name="__main__")
"""


def existing_workbook(value):
    path = Path(value).resolve()
    if path.suffix.lower() != ".xlsx" or not path.is_file():
        raise argparse.ArgumentTypeError(f"Expected an existing .xlsx file: {path}")
    return path


def rt_tolerance(value):
    minutes = float(value)
    if not math.isfinite(minutes) or minutes < 0:
        raise argparse.ArgumentTypeError("Expected a finite, non-negative tolerance in minutes.")
    return minutes


def group_width(value):
    width = int(value)
    if width < 2:
        raise argparse.ArgumentTypeError("Expected at least two columns per group.")
    return width


def parser_for_methods():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--input", required=True, type=existing_workbook, help="Source .xlsx file")
    common.add_argument("--output-dir", type=Path, default=ROOT / "output",
                        help="Directory for result workbooks (default: FP-DataHelper/output)")
    commands = parser.add_subparsers(dest="command", required=True)
    update = commands.add_parser("check-update", help="Check GitHub for a published update", allow_abbrev=False)
    update.add_argument("--skill-dir", type=Path, help="Directory containing the installed SKILL.md")
    update.add_argument("--force", action="store_true", help="Check now, bypassing the cache and automatic-check setting")

    for name, method, help_text in (
        ("sort", "Sorter-0.1.0", "Align peaks by compound name and retention time"),
        ("ri", "RI_Calculator", "Calculate retention indices against alkane standards"),
        ("threshold-simple", "CAS_to_Threshold", "Look up stored minimum thresholds by CAS"),
        ("threshold-full", "Threshold_Full", "Look up thresholds in the full database"),
        ("silicon", "Si_Marker", "Mark names that match silicon keywords"),
        ("cas", "Name_to_CAS--AromaNexus", "Look up CAS numbers using NIST (network)"),
        ("odor", "Cb_Spider--AromaNexus", "Look up odor descriptions using ChemicalBook (Chrome and network)"),
    ):
        command = commands.add_parser(name, parents=[common], help=help_text,
                                      description=help_text, allow_abbrev=False)
        command.set_defaults(method=method, interactive=False)
        if name == "sort":
            command.add_argument("--rt-tolerance", required=True, type=rt_tolerance, help="Tolerance in minutes")
            command.add_argument("--group-width", type=group_width,
                                 help="Columns per group (modern sorter can detect this)")
        if name in ("ri", "threshold-simple", "threshold-full", "odor"):
            command.add_argument("--cas-column", default="", help="CAS column letter (default: auto-detect)")
        if name in ("ri", "silicon", "cas"):
            command.add_argument("--name-column", default="", help="Name column letter (default: auto-detect)")
        if name == "ri":
            command.add_argument("--alkanes", required=True, type=existing_workbook, help="Alkane reference .xlsx file")
            command.add_argument("--formula", choices=FORMULAS, default="linear")
            command.add_argument("--aggregate", choices=AGGREGATES, default="mean")
            command.add_argument("--nist", action="store_true", help="Also query NIST when a CAS column is available")
        if name == "threshold-full":
            command.add_argument("--match", choices=("cas", "name"), help="Enable a custom lookup by CAS or name")
            command.add_argument("--selection", choices=("latest", "min", "max"))
            command.add_argument("--type-filter", choices=("all", "detection", "recognition"))
        if name == "odor":
            command.add_argument("--interactive", action="store_true", help="Allow terminal prompts for retry or skip")
    return parser


def method_parameters(args):
    parameters = {"File": str(args.input)}
    if args.command == "sort":
        parameters.update(Para1=str(args.rt_tolerance), Para2=str(args.group_width or ""))
    elif args.command == "ri":
        parameters.update(Para1=str(args.alkanes), Para2=f"{FORMULAS[args.formula]},{AGGREGATES[args.aggregate]}",
                          Para3=f"{args.cas_column},{args.name_column}", Nist=args.nist)
    elif args.command in ("cas", "silicon"):
        parameters["Para1"] = args.name_column
    else:
        parameters["Para1"] = args.cas_column
        if args.command == "threshold-full" and any((args.match, args.selection, args.type_filter)):
            if args.match == "name" and args.cas_column:
                raise ValueError("--cas-column applies to CAS lookup and cannot be combined with --match name.")
            parameters["ThresholdSettings"] = {
                "match_mode": args.match or "cas",
                "value_mode": args.selection or "latest",
                "type_filter": args.type_filter if args.type_filter in ("detection", "recognition") else "全部",
            }
    return parameters


def run_method(args):
    parameters = method_parameters(args)
    method = ROOT / "Methods" / args.method / "__init__.py"
    embedded = ROOT / "python-3.10.11-embed-amd64" / "python.exe"
    python = embedded if os.name == "nt" and embedded.is_file() else sys.executable
    command = [str(python), "-B", "-u", "-X", "utf8"]
    if os.name == "nt":
        command.extend(("-c", WINDOWS_METHOD_BOOTSTRAP))
    command.extend((str(method), json.dumps(parameters)))
    output_dir = args.output_dir.resolve()
    with TemporaryDirectory(prefix="fp-datahelper-cli-") as control:
        result = Path(control) / "result.json"
        env = {**os.environ, RESULT_PATH_ENV: str(result), OUTPUT_DIR_ENV: str(output_dir)}
        env.pop(CANCEL_PATH_ENV, None)
        completed = subprocess.run(
            command, cwd=ROOT, env=env, stdout=sys.stderr,
            stdin=None if args.interactive else subprocess.DEVNULL,
        )
        if completed.returncode:
            return completed.returncode
        if not result.is_file():
            raise ValueError("The method exited without reporting a result workbook.")
        output = Path(json.loads(result.read_text(encoding="utf-8"))["output_file"]).resolve()
        if (output.parent != output_dir or output == args.input
                or output.suffix.lower() != ".xlsx" or not output.is_file()):
            raise ValueError(f"The method did not produce a workbook in {output_dir}.")
        print(json.dumps({"output_file": str(output)}))
        return 0


def main():
    args = parser_for_methods().parse_args()
    try:
        if args.command == "check-update":
            print(json.dumps(check_update(ROOT, args.skill_dir, force=args.force)))
            return 0
        return run_method(args)
    except (OSError, TypeError, ValueError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
