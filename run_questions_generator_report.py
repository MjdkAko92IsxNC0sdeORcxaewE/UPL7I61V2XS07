import shutil
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import os

from bot_runtime import batch_limit

GetQuestions = None


def get_questions_runner_class():
    global GetQuestions
    if GetQuestions is None:
        from questions_generator import GetQuestions as runner_class

        GetQuestions = runner_class
    return GetQuestions


def get_scope_questions_pending():
    """
    Get all URLs from JSON files in the automation_pending directory.

    Returns:
        list: A list of URLs found in all JSON files
    """
    scope_questions_pending_dir = os.environ.get("SCOPE_QUESTIONS_PENDING_DIR", "scope_questions_pending")
    urls = []

    # Ensure directory exists
    if not os.path.exists(scope_questions_pending_dir):
        print(f"Directory {scope_questions_pending_dir} does not exist")
        return urls

    # Get all JSON files in the directory
    json_files = list(Path(scope_questions_pending_dir).glob("*.json"))

    if not json_files:
        print(f"No JSON files found in {scope_questions_pending_dir}")
        return urls

    # Process each JSON file
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

                # Handle both list of questions and single question objects
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and 'url' in item:
                            urls.append(item['url'])
                elif isinstance(data, dict) and 'url' in data:
                    urls.append(data['url'])

        except json.JSONDecodeError as e:
            print(f"Error parsing {json_file}: {e}")
        except Exception as e:
            print(f"Error processing {json_file}: {e}")

    return urls


def get_scope_questions_pending_files():
    scope_questions_pending_dir = os.environ.get("SCOPE_QUESTIONS_PENDING_DIR", "scope_questions_pending")
    pending_dir = Path(scope_questions_pending_dir)

    if not pending_dir.exists():
        print(f"Directory {scope_questions_pending_dir} does not exist")
        return []

    pending_files = []
    for json_file in sorted(pending_dir.glob("*.json")):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error parsing {json_file}: {e}")
            continue
        except Exception as e:
            print(f"Error processing {json_file}: {e}")
            continue

        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            print(f"Skipping {json_file}: expected a list or object")
            continue

        entries = [item for item in data if isinstance(item, dict) and item.get("url")]
        if entries:
            pending_files.append((json_file, data))

    if not pending_files:
        print(f"No JSON files found in {scope_questions_pending_dir}")

    return pending_files


def pending_urls(data):
    seen = set()
    urls = []
    for item in data:
        if not isinstance(item, dict) or item.get("questions_generated"):
            continue
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def mark_url_generated(data, url):
    for item in data:
        if isinstance(item, dict) and item.get("url") == url:
            item["questions_generated"] = True


def restore_pending_file_to_scope_questions(file_path, data=None):
    scope_questions_dir = os.environ.get("SCOPE_QUESTIONS_DIR", "scope_questions")
    os.makedirs(scope_questions_dir, exist_ok=True)

    source_path = Path(file_path)
    dest_path = Path(scope_questions_dir) / source_path.name
    if dest_path.exists():
        base_name = dest_path.stem
        extension = dest_path.suffix
        timestamp = int(time.time())
        dest_path = Path(scope_questions_dir) / f"{base_name}_{timestamp}{extension}"

    if data is None:
        shutil.move(str(source_path), str(dest_path))
    else:
        with open(dest_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        source_path.unlink(missing_ok=True)

    print(f"Restored {source_path} to {dest_path}")
    return str(dest_path)


def move_files_back_to_scope_questions():
    """Move all files from automation_pending back to automation folder"""
    scope_questions_dir = os.environ.get("SCOPE_QUESTIONS_DIR", "scope_questions")
    scope_questions_pending_dir = os.environ.get("SCOPE_QUESTIONS_PENDING_DIR", "scope_questions_pending")

    moved_files = []

    try:
        # Ensure both directories exist
        os.makedirs(scope_questions_dir, exist_ok=True)
        os.makedirs(scope_questions_pending_dir, exist_ok=True)

        # Get all files in automation_pending
        pending_files = list(Path(scope_questions_pending_dir).glob("*"))

        for file_path in pending_files:
            try:
                # Create destination path
                dest_path = os.path.join(scope_questions_dir, file_path.name)

                # Handle filename conflicts
                if os.path.exists(dest_path):
                    # Append a timestamp to make filename unique
                    base_name = file_path.stem
                    extension = file_path.suffix
                    timestamp = int(time.time())
                    dest_path = os.path.join(scope_questions_dir, f"{base_name}_{timestamp}{extension}")

                # Move the file
                shutil.move(str(file_path), dest_path)
                moved_files.append(dest_path)

            except Exception as e:
                print(f"Error moving {file_path} back to automation: {e}")
                continue

        if moved_files:
            print(f"Moved {len(moved_files)} files back to {scope_questions_dir}")
        return moved_files

    except Exception as e:
        print(f"Error in move_files_back_to_automation: {e}")
        return []



def main():
    pending_files = get_scope_questions_pending_files()
    total = sum(len(pending_urls(data)) for _, data in pending_files)

    if total == 0:
        print("No pending reports to generate")
        return

    print(f"Found {total} URLs needing reports")

    counter = 0
    generated_files = 0
    restored_files = []
    max_reports = batch_limit(500)
    report = get_questions_runner_class()(teardown=True)

    for json_file, data in pending_files:
        restore_file = False

        for url in pending_urls(data):
            if counter >= max_reports:
                restore_file = True
                break

            print(f"[{counter + 1}/{total}] Generating report for: {url}")
            try:
                saved_count = report.get_questions(url)
            except Exception as e:
                print(f"\n!!! ERROR while generating {url}: {e}")
                restore_file = True
                continue

            if not saved_count:
                print(f"\n!!! ERROR while generating {url}: no question output was saved")
                restore_file = True
                continue

            mark_url_generated(data, url)
            counter += 1
            generated_files += saved_count

        remaining = [
            item
            for item in data
            if isinstance(item, dict) and item.get("url") and not item.get("questions_generated")
        ]
        if remaining or restore_file:
            restored_files.append(restore_pending_file_to_scope_questions(json_file, data))
        else:
            Path(json_file).unlink(missing_ok=True)
            print(f"Completed and removed pending file {json_file}")

        if counter >= max_reports:
            break

    if generated_files == 0:
        raise RuntimeError("No question output was generated; restored pending files back to scope_questions")

    print(f"\n=== Completed {counter} reports into {generated_files} question files ===")
    if restored_files:
        print(f"Restored {len(restored_files)} pending files for a later retry")



if __name__ == '__main__':
    main()
