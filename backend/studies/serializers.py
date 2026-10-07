"""Projection helpers that map raw Orthanc resources to clean API responses.

No models are involved: studies are represented purely from the Orthanc REST
API response, keeping Django free of any DICOM database duplication.
"""


def serialize_study(study_resource):
    """Build the clean study representation exposed by the API.

    ``study_resource`` is the JSON returned by ``GET /studies/{id}`` (an Orthanc
    study resource). Missing/empty values are mapped to empty strings; we never
    invent metadata that Orthanc does not provide.
    """
    main_tags = study_resource.get("MainDicomTags", {}) or {}
    patient_tags = study_resource.get("PatientMainDicomTags", {}) or {}
    return {
        "study_id": study_resource.get("ID", ""),
        "patient_name": patient_tags.get("PatientName", ""),
        "patient_id": patient_tags.get("PatientID", ""),
        "study_instance_uid": main_tags.get("StudyInstanceUID", ""),
        "study_date": main_tags.get("StudyDate", ""),
        "study_description": main_tags.get("StudyDescription", ""),
    }