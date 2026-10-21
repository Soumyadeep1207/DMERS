from ai import service

def test_classification_is_explainable_and_advisory():
    result=service.classify("Flood water is rising around the bridge", "")
    assert result["value"] == "flood"
    assert 0 <= result["confidence"] <= 1 and result["limitations"]

def test_ai_never_mutates_operational_records():
    incidents=[{"id":1,"reference":"INC-1","description":"Flood near river","disaster_type":"flood"}]
    before=[dict(item) for item in incidents]
    service.assess({"description":"Flood near river","severity":"critical"}, [{"name":"Rescue Team B","capability":"flood rescue","availability":"available"}], [{"name":"Hospital","available_beds":84}])
    service.duplicates(incidents[0], incidents)
    service.forecast(incidents,"","flood",3)
    assert incidents == before
