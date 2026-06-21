db.subscribers.deleteMany({imsi: "999700000000001"});
db.subscribers.insertOne({
    "imsi": "999700000000001",
    "security": {
        "k": "465B5CE8B199B49FAA5F0A2EE238A6BC",
        "opc": "E8ED289DEBA952E4283B54E88E6183CA",
        "amf": "8000"
    },
    "ambr": {
        "downlink": {"value": 1, "unit": 3},
        "uplink":   {"value": 1, "unit": 3}
    },
    "slice": [{
        "sst": 1,
        "default_indicator": true,
        "session": [{
            "name": "internet",
            "type": 3,
            "qos": {"index": 9, "arp": {"priority_level": 8, "pre_emption_capability": 1, "pre_emption_vulnerability": 1}},
            "ambr": {"downlink": {"value": 1, "unit": 3}, "uplink": {"value": 1, "unit": 3}},
            "ue": {"addr": "10.45.0.0/16"}
        }]
    }]
});
print("SUBSCRIBER REGISTERED SUCCESSFULLY");
