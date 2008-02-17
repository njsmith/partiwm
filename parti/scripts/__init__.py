import parti
from optparse import OptionParser

def PartiOptionParser(**kwargs):
    parser = OptionParser(version="Parti v%s" % parti.__version__, **kwargs)
    return parser
