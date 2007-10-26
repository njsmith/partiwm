import parti
from optparse import OptionParser

def PartiOptionParser(**kwargs):
    version_num = ".".join(map(str, parti.__version__))
    return OptionParser(version=("Parti %s" % version_num), **kwargs)
