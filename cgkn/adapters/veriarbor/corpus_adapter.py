"""Archive reads use a host-supplied, access-checked Corpus reader."""


class CorpusArchive:
    def __init__(self, read_object):
        self.read_object = read_object

    def read(self, ref):
        return self.read_object(ref)
