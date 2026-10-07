"""
Application boundary for future study-related business logic.

IMPORTANT (Phase 2 scope):
    * No Orthanc study integration is implemented yet.
    * The Orthanc Patient -> Study -> Series -> Instance hierarchy is NOT
      duplicated here. Orthanc remains the source of truth for DICOM data.
    * This app intentionally ships with no models so that DICOM study data is
      never duplicated into Django.
"""