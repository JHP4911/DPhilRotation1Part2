import sys
import os
import gzip
import io
from optparse import OptionParser
import datetime
import time
import subprocess
from functools import wraps
import pandas as pd


def OptionParsing():
    usage = 'usage: %prog [options] -f <*.h5>'
    parser = OptionParser(usage)
    # parser.add_option('-i', '--inputFile', dest='inputMaf', default=None, help="Raw maf file.")
    # parser.add_option('-e', '--releasenotes', dest='releaseNotes', default=None, help="Release Data corresponding to MAF file.")
    parser.add_option('-s', '--skipmafstep', dest="skipParser", default=False, action="store_true", help="Skip over maf parsing (only if completed already.")
    (options, args) = parser.parse_args()
    return (options, parser)

def fn_timer(function):
    '''
    Use this as a wrapper at the top of any function you want to get run time information about.

    :param function: Function of interest.
    :return: A function to wrap around a function.
    '''
    @wraps(function)
    def function_timer(*args, **kwargs):
        t0 = time.time()
        result = function(*args, **kwargs)
        t1 = time.time()
        print ("INFO: Total time running %s: %s minutes" %
               (function.__name__, str(round((t1-t0)/60.,2)))
               )
        return result
    return function_timer

def UpdateProgress(i, n, DisplayText):
    '''
    Prints a progress bar where appropriate.

    :param i: Current Step
    :param n: Total number of steps.
    :param DisplayText: A string that you want to print out that is informative.
    :return: None
    '''
    sys.stdout.write('\r')
    j = (i + 1) / n
    sys.stdout.write("[%-20s] %d%%\t INFO: %s" % ('=' * int(20 * j), 100 * j, DisplayText))
    sys.stdout.flush()

def UpdateProgressGetN(fileName):
    if fileName[len(fileName)-1]=="z":
        cmd = "gzip -cd %s | wc -l" % (fileName)
        pipe = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout
    else:
        cmd = "wc -l %s" % (fileName)
        pipe = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout
    return(int(pipe.read().decode("utf-8").lstrip(" ").split(" ")[0]))

class PCAWGData:
    def __init__(self, FilePath, Options, CancerType, mafFile):
        self.CancerType = CancerType
        self.mafFile = mafFile
        self.metaData = None
        self.excludedSamples = None
        self.GetExcluded(FilePath)
        self.patients = None
        self.tumourIDs = None
        self.patTumorMapping = None
        self.patientMuts = {} # Patient : [Muts]
        self.patientMafs = []
        self.GetIndividualPatients()
        if Options.skipParser!=True:
            self.WriteMafFiles()

    def GetExcluded(self, FilePath):
        df = pd.read_csv(FilePath.rstrip('DataGrooming')+"PCAWGData/metadata/release_may2016.v1.4.tsv", sep="\t", header=0, index_col=False)
        df = df.loc[df['dcc_project_code'].str.contains(self.CancerType)] # Subset DataFrame for cancer type
        self.metaData = df
        df.to_csv("%s/%s.metadata.csv"%(self.mafFile.split('/%s-'%(self.CancerType))[0], self.CancerType), index=False)
        # exclDF = df.loc[df['wgs_exclusion_white_gray']=="Excluded"]



    def GetIndividualPatients(self):
        f = gzip.open(self.mafFile, 'rb')
        patients = []
        tumours = []
        mapping = {}
        for line in f:
            # Gets patients from the MAF File
            patients.append(line.decode('UTF-8').rstrip('\n').split('\t')[len(line.decode('UTF-8').rstrip('\n').split('\t')) - 1])
            # Gets tumours from the MAF File, Line 12 is patient tumor ID
            tumours.append(line.decode('UTF-8').rstrip('\n').split('\t')[12])

            # Maps patient with tumours. PatientX : TumourY1, TumourY2
            try:
                mapping[line.decode('UTF-8').rstrip('\n').split('\t')[len(line.decode('UTF-8').rstrip('\n').split('\t')) - 1]].append(line.decode('UTF-8').rstrip('\n').split('\t')[12])
            except KeyError:
                mapping.update({ line.decode('UTF-8').rstrip('\n').split('\t')[len(line.decode('UTF-8').rstrip('\n').split('\t')) - 1] : [line.decode('UTF-8').rstrip('\n').split('\t')[12]] })

            # Splits mutations into tumour sequencing specific mutations.
            try:
                self.patientMuts[line.decode('UTF-8').rstrip('\n').split('\t')[12]].append(line.decode('UTF-8').rstrip('\n'))
            except KeyError:
                self.patientMuts.update({line.decode('UTF-8').rstrip('\n').split('\t')[12]: [line.decode('UTF-8').rstrip('\n')] })
        f.close()

        patients = list(set(patients))
        tumours = list(set(tumours))
        for patient in patients:
            mapping[patient] = list(set(mapping[patient]))

        print("INFO: %s Patients: %s"%(self.CancerType, len(patients)))
        print("INFO: %s Tumours: %s"%(self.CancerType, len(tumours)))

        print("INFO: Multiple samples found for an individual patient: %s"%(len(tumours)-len(patients)))

        self.patients = patients
        self.tumourIDs = tumours
        self.patTumorMapping = mapping

    def WriteMafFiles(self):
        '''
        Only write MAF files for those that are white listed...
        '''
        n = len(self.patients)
        i=0
        for patient in self.patients:
            for tumour in self.patTumorMapping[patient]:
                self.patientMafs.append("%s/%s.%s.maf.gz"%(self.mafFile.split('/%s-'%(self.CancerType))[0],patient, tumour))
                if os.path.isfile("%s/%s.%s.maf.gz"%(self.mafFile.split('/%s-'%(self.CancerType))[0],patient, tumour)) == False:
                    f  = gzip.open("%s/%s.%s.maf.gz"%(self.mafFile.split('/%s-'%(self.CancerType))[0],patient, tumour), 'wb')
                    for mut in self.patientMuts[tumour]:
                        f.write((mut + '\n').encode('UTF-8'))
                    f.close()
                UpdateProgress(i, n, "%s.%s.maf"%(patient, tumour))
                i+=1
        self.patientMuts = None # Get rid of patient muts, no longer needed. Clear memory of this information.

    def ConvertToVCF(self):
        # TODO Create this function to do the conversions.
        pass


@fn_timer
def PrepareCancerClasses(Options, FilePath):
    with open(FilePath.rstrip("DataGrooming")+"PCAWGData/CancerTypes.txt", 'r') as inFile:
        cancerTypes = [line.rstrip('\n').replace("-","") for line in inFile.readlines()]

    allData = {}
    count = 0
    for cancer in cancerTypes:
        print("INFO: Processing %s"%(cancer))
        dataFilePath = "%sPCAWGData/Cancers/%s/%s-.snvs.indels.maf.gz"%(FilePath.rstrip("DataGrooming"), cancer, cancer)
        allData.update({cancer:PCAWGData(FilePath, Options, cancer, dataFilePath)})
        count+=1

        # if count == 1:
        #     sys.exit()

    return(allData)

if __name__=="__main__":
    FilePath = os.path.dirname(os.path.abspath(__file__))
    now = datetime.datetime.now()
    (Options, Parser) = OptionParsing()
    allOutDir = FilePath.rstrip("DataGrooming") + "PCAWGData"

    hg19GenomeSize = 3137161264 # Taken from adding up hg19 chromosome sizes.

    allData = PrepareCancerClasses(Options, FilePath)