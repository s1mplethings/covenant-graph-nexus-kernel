"""Read through the one FileRunStore; no parallel database."""


class RunEvidenceStore:
    def __init__(self, store, project_id, run_id):
        self.store, self.project_id, self.run_id = store, project_id, run_id

    def evidence(self, ref):
        return self.store.load_result(self.project_id, self.run_id, ref).as_dict()
