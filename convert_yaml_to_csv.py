import yaml
import csv

def yaml_to_csv(yaml_file_path: str, csv_file_path: str):
    with open(yaml_file_path, "r") as f:
        data = yaml.safe_load(f)

    clean_data = [
        item for item in data
        if (
        not item.get("build_metadata", {}).get("error")
        and item.get("build_metadata", {}).get("note") != "Non-supported repository host."
    )
    ]

    fieldnames = set()
    for item in clean_data:
        for key, value in item.items():
            if not isinstance(value, dict):
                fieldnames.add(key)

    field_order = ['url', 'version']
    bool_flags = sorted(fieldnames - set(field_order))
    fieldnames = field_order + bool_flags

    with open(csv_file_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in clean_data:
            row = {key: item.get(key, "") for key in fieldnames}
            writer.writerow(row)

if __name__ == "__main__":
    yaml_to_csv("go-packages.yaml", "go-packages.csv")
