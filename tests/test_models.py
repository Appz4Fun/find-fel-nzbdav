import models
from models import Candidate, TitleResult


def test_task_one_models_do_not_export_probe_result_yet():
    assert not hasattr(models, "ProbeResult")


def test_title_result_records_no_dv_disqualification():
    result = TitleResult.not_fel("Creepshow", "no_dv_4k_candidates")

    assert result.title == "Creepshow"
    assert result.verdict == "not_fel"
    assert result.reason == "no_dv_4k_candidates"
    assert result.candidates == []


def test_candidate_uses_size_for_descending_sort():
    small = Candidate(release_title="small", link="http://nzb/1", size_bytes=1)
    large = Candidate(release_title="large", link="http://nzb/2", size_bytes=2)

    assert sorted([small, large], reverse=True)[0] == large
