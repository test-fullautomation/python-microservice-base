# **************************************************************************************************************
#
#  Copyright 2020-2026 Robert Bosch GmbH
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
# **************************************************************************************************************
#
# component_test.py
#
# Nguyen Huynh Tri Cuong (MS/EMC51)
# Adapted from python-process-hub component test for MicroserviceBase.
#
# --------------------------------------------------------------------------------------------------------------
#
# --------------------------------------------------------------------------------------------------------------
#TM***
# TOC:
# [ANALYZERETURNEDVALUES]
# [ANALYZEEXCEPTIONS]
# [TESTCONFIG]
# [CODEDUMP]
# [EXECUTION]
# --------------------------------------------------------------------------------------------------------------

import os, sys, time
import colorama as col

from PythonExtensionsCollection.String.CString import CString
from PythonExtensionsCollection.File.CFile import CFile
from PythonExtensionsCollection.Utils.CUtils import *

from libs.CConfig import CConfig
from libs.CGenCode import CGenCode

from testconfig.TestConfig import *

# Defined AFTER the wildcard imports above so PythonExtensionsCollection's
# own VERSION / VERSION_DATE constants don't shadow these.
VERSION      = "0.1.0"
VERSION_DATE = "10.05.2026"

# --------------------------------------------------------------------------------------------------------------
# !!! the system under test !!!
# MicroserviceBase - gRPC + Consul + Nomad scaffold generator and runtime framework
# --------------------------------------------------------------------------------------------------------------

col.init(autoreset=True)

COLBR = col.Style.BRIGHT + col.Fore.RED
COLBY = col.Style.BRIGHT + col.Fore.YELLOW
COLBG = col.Style.BRIGHT + col.Fore.GREEN
COLBB = col.Style.BRIGHT + col.Fore.BLUE

SUCCESS = 0
ERROR   = 1

# --------------------------------------------------------------------------------------------------------------

def printerror(sMsg, prefix=None):
   if prefix is None:
      sError = COLBR + f"Error: {sMsg}!\n\n"
   else:
      sError = COLBR + f"{prefix}:\n{sMsg}!\n\n"
   sys.stderr.write(sError)

# --------------------------------------------------------------------------------------------------------------
# [ANALYZERETURNEDVALUES]

def AnalyzeReturnedValues(EXPECTEDRETURN=None, actualReturned=None):

   sMethod = "AnalyzeReturnedValues"

   listErrors = []

   if ( (EXPECTEDRETURN is None) and (actualReturned is None) ):
      # returned == expected => check passed (in case of len(listErrors) == 0)
      pass
   elif ( (EXPECTEDRETURN is not None) and (actualReturned is None) ):
      sResult  = "MicroserviceBase returned None, but values are expected"
      listErrors.append(sResult)
   elif ( (EXPECTEDRETURN is None) and (actualReturned is not None) ):
      sResult  = "MicroserviceBase returned values, but values are not expected"
      listErrors.append(sResult)
   else:
      # both EXPECTEDRETURN and actualReturned are not None => content needs to be compared

      listSplitLines = EXPECTEDRETURN.splitlines()
      listExpectedLines = []
      for sLine in listSplitLines:
         if sLine != "":
            listExpectedLines.append(sLine)

      listReturnedLines = actualReturned.splitlines() if isinstance(actualReturned, str) else [actualReturned]

      # check number of lines
      nNrOfLinesReturned = len(listReturnedLines)
      nNrOfLinesExpected = len(listExpectedLines)
      if nNrOfLinesReturned != nNrOfLinesExpected:
         bSuccess = False
         sResult  = f"MicroserviceBase value counter mismatch! Expected: {nNrOfLinesExpected} values, but returned: {nNrOfLinesReturned} values"
         listErrors.append(sResult)
         print("MicroserviceBase returned:")
         print()
         print(actualReturned)
         print()
         return listErrors, bSuccess, sResult

      # compare content line by line
      for nIndex, sLineReturned in enumerate(listReturnedLines):
         sLineExpected = listExpectedLines[nIndex]
         if sLineReturned != sLineExpected:
            sResult    = f"Found deviating return values\n(1) '{sLineExpected}'   > (expected)\n(2) '{sLineReturned}'   > (returned)"
            listErrors.append(sResult)

   if len(listErrors) == 0:
      bSuccess = True
      if EXPECTEDRETURN is None:
         sResult  = "No values returned from MicroserviceBase (like expected)."
      else:
         sResult  = "MicroserviceBase returned expected values."
   else:
      bSuccess = False
      sResult  = "MicroserviceBase did not return expected values."

   return listErrors, bSuccess, sResult

# eof def AnalyzeReturnedValues(EXPECTEDRETURN=None, actualReturned=None):

# --------------------------------------------------------------------------------------------------------------
# [ANALYZEEXCEPTIONS]

def AnalyzeExceptions(EXPECTEDEXCEPTION=None, sException=None):

   sMethod = "AnalyzeExceptions"

   listErrors = []

   if ( (EXPECTEDEXCEPTION is None) and (sException is None) ):
      pass
   elif ( (EXPECTEDEXCEPTION is not None) and (sException is None) ):
      sResult  = "MicroserviceBase threw no exception, but an exception is expected"
      listErrors.append(sResult)
   elif ( (EXPECTEDEXCEPTION is None) and (sException is not None) ):
      sResult  = "MicroserviceBase threw an exception, but an exception is not expected"
      listErrors.append(sResult)
   else:
      if EXPECTEDEXCEPTION not in sException:
         bSuccess = False
         sResult  = f"MicroserviceBase exception mismatch! Expected exception:\n'{EXPECTEDEXCEPTION}',\nbut thrown:\n'{sException}'"
         listErrors.append(sResult)

   if len(listErrors) == 0:
      bSuccess = True
      if EXPECTEDEXCEPTION is None:
         sResult  = "No exception thrown from MicroserviceBase (like expected)."
      else:
         sResult  = "MicroserviceBase threw expected exception."
   else:
      bSuccess = False
      sResult  = "MicroserviceBase did not throw expected exception."

   return listErrors, bSuccess, sResult

# eof def AnalyzeExceptions(EXPECTEDEXCEPTION=None, sException=None):


# --------------------------------------------------------------------------------------------------------------
# [TESTCONFIG]

# -- initialize and dump test configuration

oConfig = None
try:
   oConfig = CConfig(os.path.abspath(__file__))
except Exception as ex:
   print()
   printerror(CString.FormatResult("(main)", None, str(ex)))
   print()
   sys.exit(ERROR)

# update version and date of this app
oConfig.Set("VERSION", VERSION)
oConfig.Set("VERSION_DATE", VERSION_DATE)
THISSCRIPTNAME = oConfig.Get('THISSCRIPTNAME')
THISSCRIPTFULLNAME = f"{THISSCRIPTNAME} v. {VERSION} / {VERSION_DATE}"
oConfig.Set("THISSCRIPTFULLNAME", THISSCRIPTFULLNAME)

# add information about system under test
try:
   from MicroserviceBase.version import VERSION as MSB_VERSION, VERSION_DATE as MSB_VERSION_DATE
   SUT_FULL_NAME = f"MicroserviceBase v. {MSB_VERSION} / {MSB_VERSION_DATE}"
   oConfig.Set("SUT_FULL_NAME", SUT_FULL_NAME)
except:
   pass

# dump configuration values to screen
listConfigLines = oConfig.DumpConfig()

CONFIGDUMP = oConfig.Get('CONFIGDUMP')
if CONFIGDUMP is True:
   # if that's all, we have nothing more to do
   sys.exit(SUCCESS)


# --------------------------------------------------------------------------------------------------------------
# [PRELIMINARIES]
# --------------------------------------------------------------------------------------------------------------
#TM***

# -- access to configuration

THISSCRIPT         = oConfig.Get('THISSCRIPT')
THISSCRIPTNAME     = oConfig.Get('THISSCRIPTNAME')
TESTCONFIGPATH     = oConfig.Get('TESTCONFIGPATH')
TESTFILESPATH      = oConfig.Get('TESTFILESPATH')
OSNAME             = oConfig.Get('OSNAME')
PLATFORMSYSTEM     = oConfig.Get('PLATFORMSYSTEM')
PYTHON             = oConfig.Get('PYTHON')
PYTHONVERSION      = oConfig.Get('PYTHONVERSION')
TESTLOGFILESFOLDER = oConfig.Get('TESTLOGFILESFOLDER')
SELFTESTLOGFILE    = oConfig.Get('SELFTESTLOGFILE')
TESTID             = oConfig.Get('TESTID')

# -- start logging
oSelfTestLogFile = CFile(SELFTESTLOGFILE)
NOW = time.strftime('%d.%m.%Y - %H:%M:%S')
oSelfTestLogFile.Write(f"{THISSCRIPTNAME} started at: {NOW}\n")
oSelfTestLogFile.Write(listConfigLines) # from DumpConfig() called above
oSelfTestLogFile.Write()

# -- prepare TESTIDs

# ('listofdictUsecases' is imported directly from test/testconfig/TestConfig.py)

TESTID = oConfig.Get('TESTID')

if TESTID is not None:
   listTESTIDs = TESTID.split(';')
   listofdictUsecasesSubset = []
   for sTESTID in listTESTIDs:
      sTESTID = sTESTID.strip()
      for dictUsecase in listofdictUsecases:
         if sTESTID == dictUsecase['TESTID']:
            listofdictUsecasesSubset.append(dictUsecase)
   # eof for sTESTID in listTESTIDs:
   if len(listofdictUsecasesSubset) == 0:
      bSuccess = False
      sResult  = f"Test ID '{TESTID}' not defined"
      sResult  = CString.FormatResult(THISSCRIPTNAME, bSuccess, sResult)
      print()
      printerror(sResult)
      print()
      printerror(sResult)
      oSelfTestLogFile.Write(sResult, 1)
      del oSelfTestLogFile
      sys.exit(ERROR)
   del listofdictUsecases
   listofdictUsecases = listofdictUsecasesSubset
# eof if TESTID is not None:

# --------------------------------------------------------------------------------------------------------------

# -- check for duplicate test IDs
# Test IDs are used to identify and select test cases. They have to be unique.

listIDs = []
listDuplicates = []
for dictUsecase in listofdictUsecases:
   TESTID = dictUsecase['TESTID']
   if TESTID in listIDs:
      listDuplicates.append(TESTID)
   else:
      listIDs.append(TESTID)
# eof for dictUsecase in listofdictUsecases:
if len(listDuplicates) > 0:
   sDuplicates = "[" + ", ".join(listDuplicates) + "]"
   bSuccess = False
   sResult  = f"Duplicate test IDs found in test configuration: {sDuplicates}\nTest IDs are used to identify and select test cases. They have to be unique"
   sResult  = CString.FormatResult(THISSCRIPTNAME, bSuccess, sResult)
   print()
   printerror(sResult)
   print()
   oSelfTestLogFile.Write(sResult, 1)
   del oSelfTestLogFile
   sys.exit(ERROR)


# --------------------------------------------------------------------------------------------------------------
# [CODEDUMP]
# special function (with premature end of execution = no test execution)
# --------------------------------------------------------------------------------------------------------------
#TM***

CODEDUMP = oConfig.Get('CODEDUMP')
if CODEDUMP is True:
   oCodeGenerator = None
   try:
      oCodeGenerator = CGenCode(oConfig)
   except Exception as ex:
      bSuccess = None
      sResult  = str(ex)
      sResult  = CString.FormatResult(THISSCRIPTNAME, bSuccess, sResult)
      print()
      printerror(sResult)
      print()
      oSelfTestLogFile.Write(sResult, 1)
      del oSelfTestLogFile
      sys.exit(ERROR)

   bSuccess, sResult = oCodeGenerator.GenCode()
   if bSuccess is not True:
      sResult = CString.FormatResult(THISSCRIPTNAME, bSuccess, sResult)
      print()
      printerror(sResult)
      print()
      oSelfTestLogFile.Write(sResult, 1)
      del oSelfTestLogFile
      sys.exit(ERROR)

   print(COLBG + f"{sResult}\n")

   # after code dump nothing more to do here
   sys.exit(SUCCESS)


# --------------------------------------------------------------------------------------------------------------
# [EXECUTION]
# --------------------------------------------------------------------------------------------------------------
#TM***

print("Executing test cases")
print()

nNrOfUsecases = len(listofdictUsecases)

# -- initialize test counter
nCntUsecases        = 0
nCntPassedUsecases  = 0
nCntFailedUsecases  = 0
nCntUnknownUsecases = 0
nCntSkippedUsecases = 0

listTestsNotPassed = []

for dictUsecase in listofdictUsecases:

   nCntUsecases = nCntUsecases + 1

   # get required parameters
   TESTID            = dictUsecase['TESTID']
   DESCRIPTION       = dictUsecase['DESCRIPTION']
   EXPECTATION       = dictUsecase['EXPECTATION']
   SECTION           = dictUsecase['SECTION']
   SUBSECTION        = dictUsecase['SUBSECTION']
   TESTFILE          = dictUsecase['TESTFILE']
   EXPECTEDEXCEPTION = dictUsecase['EXPECTEDEXCEPTION']
   EXPECTEDRETURN    = dictUsecase['EXPECTEDRETURN']

   # get optional parameters
   HINT = None
   if "HINT" in dictUsecase:
      HINT = dictUsecase['HINT']
   COMMENT = None
   if "COMMENT" in dictUsecase:
      COMMENT = dictUsecase['COMMENT']
   USERAWPATH = False
   if "USERAWPATH" in dictUsecase:
      USERAWPATH = dictUsecase['USERAWPATH']

   if USERAWPATH is not True:
      TESTFILE = CString.NormalizePath(TESTFILE, sReferencePathAbs=TESTFILESPATH)

   # get derived parameters
   TESTFULLNAME    = f"{TESTID}-({SECTION})-[{SUBSECTION}]"
   TESTLOGFILE_TXT = f"{TESTLOGFILESFOLDER}/{TESTFULLNAME}.log"

   sOut = f"====== [START OF TEST] : '{TESTFULLNAME}' / ({nCntUsecases}/{nNrOfUsecases})"
   print(COLBY + sOut)
   print()
   oSelfTestLogFile.Write(sOut, 1)
   sOut = f"   [TESTFILE] : '{TESTFILE}'"
   print(COLBY + sOut)
   oSelfTestLogFile.Write(sOut)
   sOut = f"[DESCRIPTION] : {DESCRIPTION}"
   print(COLBY + sOut)
   oSelfTestLogFile.Write(sOut)
   sOut = f"[EXPECTATION] : {EXPECTATION}"
   print(COLBY + sOut)
   oSelfTestLogFile.Write(sOut)
   if COMMENT is not None:
      sOut = f"    [COMMENT] : {COMMENT}"
      print(COLBY + sOut)
      oSelfTestLogFile.Write(sOut)
   if HINT is not None:
      sOut = f"       [HINT] : {HINT}"
      print(COLBY + sOut)
      oSelfTestLogFile.Write(sOut)
   print()
   oSelfTestLogFile.Write()

   # --------------------------------------------------------------------------------------------------------------

   actualReturned = None
   sException   = None
   try:
      # Execute the test file with the MicroserviceBase test utilities
      import importlib.util
      import inspect

      spec = importlib.util.spec_from_file_location("test_module", TESTFILE)
      test_module = importlib.util.module_from_spec(spec)
      spec.loader.exec_module(test_module)

      # Find test functions in the module (function's name is test)
      test_functions = [func for name, func in inspect.getmembers(test_module, inspect.isfunction)
                       if name == 'test']

      if test_functions:
         test_function = test_functions[0]
         actualReturned = test_function()

         # If there was an exception but no exception is expected, handle it as error
         if isinstance(actualReturned, tuple) and len(actualReturned) == 2:
            actualReturned, sException = actualReturned
      else:
         # No test function found
         sErrorMessage = f"No function named 'test' found in {TESTFILE}"
         printerror(sErrorMessage)
         oSelfTestLogFile.Write(sErrorMessage, 1)
         actualReturned = None
         nCntFailedUsecases = nCntFailedUsecases + 1
         continue
   except Exception as reason:
      sException = f"'{reason}'"
      printerror(sException, "MicroserviceBase threw exception")
      oSelfTestLogFile.Write("MicroserviceBase threw exception:", 1)
      oSelfTestLogFile.Write(sException)
      oSelfTestLogFile.Write()

   # //////////////////////////////////////////////////////////////////////////////////////////////////////////////

   oSelfTestLogFile.Write("MicroserviceBase returned:", 1)
   oSelfTestLogFile.Write(actualReturned)

   # -- SKIPPED convention: a testfile may return a string starting with
   # "SKIPPED:" to signal that an environmental prerequisite is missing
   # (e.g. consul / nomad agent not on PATH).  Counted separately from
   # PASSED / FAILED / UNKNOWN so it stays visible without breaking CI.
   if isinstance(actualReturned, str) and actualReturned.startswith("SKIPPED:"):
      nCntSkippedUsecases = nCntSkippedUsecases + 1
      sOut = f"    Test '{TESTFULLNAME}' SKIPPED ({actualReturned[len('SKIPPED:'):].strip()})"
      print(COLBB + sOut)
      print()
      oSelfTestLogFile.Write(sOut)
      oSelfTestLogFile.Write()
      listTestsNotPassed.append(TESTFULLNAME)
      continue # for dictUsecase in listofdictUsecases:

   if ( (EXPECTEDEXCEPTION is None) and (EXPECTEDRETURN is None) ):
      nCntUnknownUsecases = nCntUnknownUsecases + 1
      sOut = f"    Test '{TESTFULLNAME}' UNKNOWN (because expected values are not defined)"
      print(COLBB + sOut)
      print()
      oSelfTestLogFile.Write()
      oSelfTestLogFile.Write(sOut)
      oSelfTestLogFile.Write()
      listTestsNotPassed.append(TESTFULLNAME)
      print("MicroserviceBase returned:")
      print()
      print(actualReturned)
      print()
      continue # for dictUsecase in listofdictUsecases:

   listErrors = []

   listErrorsReturnedValues, bSuccess, sResult = AnalyzeReturnedValues(EXPECTEDRETURN, actualReturned)
   listErrors.extend(listErrorsReturnedValues)
   if bSuccess is True:
      # intermediate result
      print(sResult)
      print()
      oSelfTestLogFile.Write()
      oSelfTestLogFile.Write(sResult)
      oSelfTestLogFile.Write()

   listErrorsExceptions, bSuccess, sResult = AnalyzeExceptions(EXPECTEDEXCEPTION, sException)
   listErrors.extend(listErrorsExceptions)
   if bSuccess is True:
      # intermediate result
      print(sResult)
      print()
      oSelfTestLogFile.Write(sResult)
      oSelfTestLogFile.Write()

   # -- final result
   if len(listErrors) == 0:
      nCntPassedUsecases = nCntPassedUsecases + 1
      sOut = f"    Test '{TESTFULLNAME}' PASSED"
      print(COLBG + sOut)
      print()
      oSelfTestLogFile.Write(sOut)
      oSelfTestLogFile.Write()
   else:
      nCntFailedUsecases = nCntFailedUsecases + 1
      sErrors = "\n".join(listErrors)
      printerror(sErrors)
      oSelfTestLogFile.Write(sErrors, 1)
      printerror(f"Test '{TESTFULLNAME}' FAILED\n\n[DESCRIPTION]: {DESCRIPTION}\n[EXPECTATION]: {EXPECTATION}")
      oSelfTestLogFile.Write("\n" + f"    Test '{TESTFULLNAME}' FAILED", 1)
      listTestsNotPassed.append(TESTFULLNAME)

# eof for dictUsecase in listofdictUsecases:

# --------------------------------------------------------------------------------------------------------------

# paranoia check
if ( (nCntPassedUsecases + nCntFailedUsecases + nCntUnknownUsecases + nCntSkippedUsecases != nCntUsecases) or (nNrOfUsecases != nCntUsecases) ):
   print()
   sOut = CString.FormatResult(THISSCRIPTNAME, bSuccess=None, sResult="Internal counter mismatch")
   printerror(sOut)
   oSelfTestLogFile.Write(sOut)
   sOut = f"Defined  : {nNrOfUsecases}"
   printerror(sOut)
   oSelfTestLogFile.Write(sOut)
   sOut = f"Executed : {nCntUsecases}"
   printerror(sOut)
   oSelfTestLogFile.Write(sOut)
   sOut = f"PASSED   : {nCntPassedUsecases}"
   printerror(sOut)
   oSelfTestLogFile.Write(sOut)
   sOut = f"FAILED   : {nCntFailedUsecases}"
   printerror(sOut)
   oSelfTestLogFile.Write(sOut)
   sOut = f"UNKNOWN  : {nCntUnknownUsecases}"
   printerror(sOut)
   oSelfTestLogFile.Write(sOut)
   print()
   del oSelfTestLogFile
   sys.exit(ERROR)

# --------------------------------------------------------------------------------------------------------------

# -- component test result (over all test cases)

if len(listTestsNotPassed) > 0:
   sOut = "Tests that are not PASSED:"
   oSelfTestLogFile.Write(sOut + "\n")
   print(COLBY + sOut)
   print()
   for sTest in listTestsNotPassed:
      sOut = f"- {sTest}"
      oSelfTestLogFile.Write(sOut)
      print(sOut)
   oSelfTestLogFile.Write()
   print()

nReturn = ERROR

if nCntUsecases == 0:
   sOut = "Nothing executed - but why?" # should not happen
   oSelfTestLogFile.Write(sOut, 1)
   printerror(sOut)
   nReturn = ERROR
elif ( (nCntFailedUsecases == 0) and (nCntUnknownUsecases == 0) ):
   if nCntSkippedUsecases > 0:
      sOut = f"Component test PASSED ({nCntSkippedUsecases} skipped)"
   else:
      sOut = f"Component test PASSED"
   oSelfTestLogFile.Write(sOut, 1)
   print(COLBG + sOut)
   print()
   nReturn = SUCCESS
else:
   sOut = f"Component test FAILED"
   oSelfTestLogFile.Write(sOut, 1)
   printerror(sOut)
   nReturn = ERROR

sOut = f"Defined : {nNrOfUsecases}"
print(COLBY + sOut)
oSelfTestLogFile.Write(sOut)
sOut = f"PASSED  : {nCntPassedUsecases}"
print(COLBY + sOut)
oSelfTestLogFile.Write(sOut)
sOut = f"FAILED  : {nCntFailedUsecases}"
print(COLBY + sOut)
oSelfTestLogFile.Write(sOut)
sOut = f"UNKNOWN : {nCntUnknownUsecases}"
print(COLBY + sOut)
oSelfTestLogFile.Write(sOut)
sOut = f"SKIPPED : {nCntSkippedUsecases}"
print(COLBY + sOut)
oSelfTestLogFile.Write(sOut)

print()

del oSelfTestLogFile

sys.exit(nReturn)

# --------------------------------------------------------------------------------------------------------------
