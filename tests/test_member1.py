import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from member1_infra.ingestion import create_sample_telemetry, upload_file
from member1_infra.cloud_sync import export


def test_ingestion():
    file = create_sample_telemetry()
    res = upload_file(file)
    assert res.status_code == 200


def test_cloud_audit():
    path = export("audit")
    assert os.path.exists(path)


def test_cloud_benchmark():
    path = export("benchmark")
    assert os.path.exists(path)


if __name__ == "__main__":
    test_ingestion()
    test_cloud_audit()
    test_cloud_benchmark()
    print("ALL TESTS PASSED")
