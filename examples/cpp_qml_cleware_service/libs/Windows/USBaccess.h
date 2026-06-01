// DLL class definitions for access to USB HID devices
//
// (C) 2001-2016 Copyright Cleware GmbH
// All rights reserved
//
// History:
// 05.01.2001			ws	Initial coding
// 17.07.2001			ws	cleanup interface
// ...
// 25.01.2007	3.4.5	ws	indication of timeout with humi22 (-200.) missing (345)
// 24.10.2007	3.4.6	ws	implemented GetMultiConfig
// 09.11.2009	3.5.0	ws	added Counter and Mouse devices
// 03.05.2010	4.0.0	ws	ported to VS2008, added isAmpel
// 15.08.2010	4.0.1	ws	switch 3/4 now Switch0-Type so Get/SetMultiSwitch must handle this dev type
// 08.03.2011	4.0.5	ws	simple GetTemperature for use with LabView
// 14.04.2011	4.0.6	ws	simple GetHumidity for use with LabView
// 14.04.2011	4.0.7	ws	no default reset every time the new humi and temp interface are called
// 06.08.2012	4.0.9	ws	IOX interface extended, internal use only
// 01.10.2012	4.3.0	ws	new ADC functions
// 12.01.2013	4.3.2	ws	support for new device generation, added IsLuminus
// 12.01.2013	4.3.3	ws	Inoage Version
// 11.03.2013	4.3.4	ws	Fujitsu device handling 
// 22.05.2013	4.3.5	ws	indicate new controller
// 18.10.2013	4.3.6	ws	added idetec device
// 18.10.2013	4.3.7	ws	added SetTempOffset(...) ; // returns 1 if ok or 0 in case of an error
// 08.05.2014	4.3.8	ws	IsCutter detection error fixed
// 16.06.2014	4.3.9	ws	AutoReset/Watchdog detection with 813 fixed
// 01.09.2014	4.4.0	ws	IdeTec support
// 10.09.2014	4.4.1	ws	Humidity got new formular for more precise values
// 02.02.2015	4.4.2	ws	IdeTec support, special deice types, added second temp sensor, IOX disconnect detection faster
// 29.04.2015	4.4.3	ws	Bugfix in GetSeqSwitch for Conttact devices
// 05.06.2015	4.4.4	ws	GetADC covers new 613 ADC device
// 04.08.2015	4.4.5	ws	GetOnlineOnTime changed to get more info to WatchdogXP
// 03.02.2016	4.5.0	ws	Support device selection using serial number - if deviceNo > 256 then this is a serial number
// 14.04.2016	4.5.1	ws	Added virtual device for internal use
// 13.07.2016	4.5.2	ws	Added more KnoxBox for internal use, extend IOX read to three read tries
// 14.09.2016	4.5.3	ws	Added some internal serial nmber handling
// 10.01.2017	4.5.4	ws	Key16 device reactivated 
// 14.02.2017	4.5.5	ws	Added support for ForisControl V12, fixed small multiread bug
// 14.02.2017	4.5.6	ws	fixed small ForisControl bug
// 25.09.2017	5.0.0	ws	added Monitored Switch support
// 10.11.2017	5.0.1	ws	added hx71 ADC support
// 15.11.2017	5.0.2	ws	added new IR device
// 11.12.2017	5.0.3	ws	extend counter device support, get frequency
// 08.02.2018	5.0.4	ws	fixed bugs in C definitions
// 08.02.2018	5.1.1	ws	increase ADC functionality, getADC returns NAN in case of an error
// 14.02.2018	5.1.2	ws	fixed GetMultiConfig bug


// The following ifdef block is the standard way of creating macros which make exporting 
// from a DLL simpler. All files within this DLL are compiled with the USBACCESS_EXPORTS
// symbol defined on the command line. this symbol should not be defined on any project
// that uses this DLL. This way any other project whose source files include this file see 
// USBACCESS_API functions as being imported from a DLL, wheras this DLL sees symbols
// defined with this macro as being exported.

// USBaccess.h : Hauptheaderdatei für die USBaccess-DLL
//

#pragma once


#ifdef USBACCESS_EXPORTS
#define USBACCESS_API __declspec(dllexport)
#else
#define USBACCESS_API __declspec(dllimport)
#endif

#ifdef CC_USE_DEBUGWRITE
#ifndef __AFXWIN_H__
	#error "'stdafx.h' vor dieser Datei für PCH einschließen"
#endif
#endif	// CC_USE_DEBUGWRITE

const int USBaccessVersion = 512 ;

#ifdef __cplusplus

class USBACCESS_API CUSBaccess {
	public:
		enum USBactions {		LEDs=0, EEwrite=1, EEread=2, Reset=3, KeepCalm=4, GetInfo=5, 
								StartMeasuring=6,		// USB-Humidity
								Configure=7,			// USB-IO16-V10, USB-Counter-V05
								Display=8,				// USB/Display
								RunPoint=10,			// USB-Encoder
								ContactWrite=11,		// 613
								ContactRead=12,			// 613
								EEread4=13,				// 613
								Programm=15				// Transfer new Firmware (internal use only)
								} ;
		enum USBInfoType {		OnlineTime=1, OnlineCount=2, ManualTime=3, ManualCount=4 } ;
		enum LED_IDs {			LED_0=0, LED_1=1, LED_2=2, LED_3=3 } ;
		enum COUNTER_IDs {		COUNTER_0=0, COUNTER_1=1 } ;
		enum SWITCH_IDs {		SWITCH_0=0x10, SWITCH_1=0x11, SWITCH_2=0x12, SWITCH_3=0x13,
								SWITCH_4=0x14, SWITCH_5=0x15, SWITCH_6=0x16, SWITCH_7=0x17,
								SWITCH_8=0x18, SWITCH_9=0x19, SWITCH_10=0x1a, SWITCH_11=0x1b,
								SWITCH_12=0x1c, SWITCH_13=0x1d, SWITCH_14=0x1e, SWITCH_15=0x1f
								} ;
		enum USBtype_enum {		ILLEGAL_DEVICE=0,
								LED_DEVICE=0x01,
								POWER_DEVICE=0x02,
								DISPLAY_DEVICE=0x03,
								WATCHDOG_DEVICE=0x05,
								AUTORESET_DEVICE=0x06,
								WATCHDOGXP_DEVICE=0x07,
								SWITCH1_DEVICE=0x08,
								SWITCH2_DEVICE=0x09, SWITCH3_DEVICE=0x0a, SWITCH4_DEVICE=0x0b,
								SWITCH5_DEVICE=0x0c, SWITCH6_DEVICE=0x0d, SWITCH7_DEVICE=0x0e, SWITCH8_DEVICE=0x0f,
								TEMPERATURE_DEVICE=0x10, 
								TEMPERATURE2_DEVICE=0x11,
								TEMPERATURE5_DEVICE=0x15, 
								HUMIDITY1_DEVICE=0x20, HUMIDITY2_DEVICE=0x21,
								SWITCHX_DEVICE=0x28,		// new switch 3,4,8
								CONTACT00_DEVICE=0x30, CONTACT01_DEVICE=0x31, CONTACT02_DEVICE=0x32, CONTACT03_DEVICE=0x33, 
								CONTACT04_DEVICE=0x34, CONTACT05_DEVICE=0x35, CONTACT06_DEVICE=0x36, CONTACT07_DEVICE=0x37, 
								CONTACT08_DEVICE=0x38, CONTACT09_DEVICE=0x39, CONTACT10_DEVICE=0x3a, CONTACT11_DEVICE=0x3b, 
								CONTACT12_DEVICE=0x3c, CONTACT13_DEVICE=0x3d, CONTACT14_DEVICE=0x3e, CONTACT15_DEVICE=0x3f, 
								F4_DEVICE=0x40, 
								KEYC01_DEVICE=0x41, KEYC16_DEVICE=0x42, MOUSE_DEVICE=0x43,
								KEYC813_DEVICE=0x48, KEYC816_DEVICE=0x48, MOUSE813_DEVICE=0x4a,
								ADC0800_DEVICE = 0x50, ADC0801_DEVICE = 0x51, ADC0802_DEVICE = 0x52, ADC0803_DEVICE = 0x53,
								ADC0804_DEVICE = 0x54, ADC0805_DEVICE = 0x55, ADC0806_DEVICE = 0x56, ADC0807_DEVICE = 0x57, 
								ADC0808_DEVICE = 0x58, ADC0809_DEVICE = 0x59, ADC0810_DEVICE = 0x5a, ADC0811_DEVICE = 0x5b, 
								ADC0812_DEVICE = 0x5c, ADC0813_DEVICE = 0x5d, ADC0814_DEVICE = 0x5e, ADC0815_DEVICE = 0x5f,
								COUNTER00_DEVICE=0x60, COUNTER01_DEVICE=0x61, COUNTER02_DEVICE=0x62,
								CONTACTTIMER00_DEVICE=0x70, CONTACTTIMER01_DEVICE=0x71, CONTACTTIMER02_DEVICE=0x72, 
								ENCODER01_DEVICE=0x80,
								IDETEC_DEVICE=0x81,				// for internal use only
								IR_DEVICE=0x90,					// Infrared Sender/Receiver
								LOGIC_DEVICE = 0x100,		// for internal use only, collects 00-07
								LOGIC00_DEVICE = 0x110, LOGIC01_DEVICE = 0x111, LOGIC02_DEVICE = 0x112, LOGIC03_DEVICE = 0x113, 	// for internal use only
								LOGIC04_DEVICE = 0x114, LOGIC05_DEVICE = 0x115, LOGIC06_DEVICE = 0x116, LOGIC07_DEVICE = 0x117, 	// for internal use only
								BUTTON_NODEVICE=0x1000
								} ;
	private:
		class CUSBaccessBasic *	X	;	// avoid export of internal USB variables

	public:
		CUSBaccess(void) ;
		virtual ~CUSBaccess(void) ;		// maybe used as base class

		virtual int			OpenCleware(void) ;			// returns number of found Cleware devices
		virtual int			CloseCleware(void) ;		// close all Cleware devices
		virtual int			Recover(int devNum) ;	// try to find disconnected devices, returns true if succeeded
		virtual HANDLE		GetHandle(int deviceNo) ;
		virtual int			GetValue(int deviceNo, unsigned char *buf, int bufsize) ;
		virtual int			SetValue(int deviceNo, unsigned char *buf, int bufsize) ;
		virtual int			SetLED(int deviceNo, enum LED_IDs Led, int value) ;	// value: 0=off 7=medium 15=highlight
		virtual int			SetSwitch(int deviceNo, enum SWITCH_IDs Switch, int On) ;	//	On: 0=off, 1=on
		virtual int			GetSwitch(int deviceNo, enum SWITCH_IDs Switch) ;			//	On: 0=off, 1=on, -1=error
		virtual int			GetSeqSwitch(int deviceNo, enum SWITCH_IDs Switch, int seqNum) ;		//	On: 0=off, 1=on, -1=error
		virtual int			GetSwitchConfig(int deviceNo, int *switchCount, int *buttonAvailable) ;
		virtual int			GetTemperature(int deviceNo, double *Temperature, int *timeID, int subDevice=0) ;
		virtual float		GetTemperature(int deviceNo) ;
		virtual int			GetHumidity(int deviceNo, double *Humidity, int *timeID, int subDevice=0) ;
		virtual float		GetHumidity(int deviceNo) ;
		virtual int			SelectADC(int deviceNo, int subDevice) ;
		virtual float		GetADC(int deviceNo, int sequenceNumber, int subDevice) ;
		virtual int			ResetDevice(int deviceNo) ;
		virtual int			StartDevice(int deviceNo) ;	
		virtual int			CalmWatchdog(int deviceNo, int minutes, int minutes2restart) ;
		virtual int			GetVersion(int deviceNo) ;
		virtual int			GetUSBType(int deviceNo) ;
		virtual int			GetSerialNumber(int deviceNo) ;
		virtual int			GetDLLVersion() { return USBaccessVersion ; }
		virtual int			GetManualOnCount(int deviceNo) ;		// returns how often switch is manually turned on
		virtual int			GetManualOnTime(int deviceNo) ;			// returns how long (seconds) switch is manually turned on
		virtual int			GetOnlineOnCount(int deviceNo) ;		// returns how often switch is turned on by USB command
		virtual int			GetOnlineOnTime(int deviceNo) ;			// returns how long (seconds) switch is turned on by USB command
		virtual int			GetMultiSwitch(int deviceNo, unsigned long int *mask, unsigned long int *value, int seqNumber) ;
		virtual int			SetMultiSwitch(int deviceNo, unsigned long int value) ;
		virtual int			SetMultiConfig(int deviceNo, unsigned long int directions) ;
		virtual int			GetCounter(int deviceNo, enum COUNTER_IDs counterID) ;	// COUNTER_IDs ununsed until now
		virtual int			SetCounter(int deviceNo, int counter, enum COUNTER_IDs counterID) ;	//  -1=error, COUNTER_IDs ununsed until now
		virtual int			SyncDevice(int deviceNo, unsigned long int mask) ;	
		virtual int			SetDisplay(int deviceNo, int byte1, int byte2, int segmentDirect=0) ;	//  1=ok, 0=error
		virtual int			GetMultiConfig(int deviceNo) ;	// returns directions
		virtual int			IsCutter(int deviceNo) ;		// return true if this is a cutter device
		virtual int			IsAlarm(int deviceNo) ;			// return true if this is a alarm buzzer device
		virtual int			IsAmpel(int deviceNo) ;			// return true if this is an ampel (traffic light) device
		virtual int			IsLuminus(int deviceNo) ;		// return true if this is a Luminus device
		virtual int			IsSolidState(int deviceNo) ;	// return true if device is low voltage non relais switch
		virtual int			GetHWversion(int deviceNo) ;	// return HWversion (0 for pre 2014 designed devices, 13 for new devices)
		virtual int			IsWatchdogInvert(int deviceNo) ;			// return true if watchdog inverted
		virtual int			IOX(int deviceNo, int addr, int data) ;		// for internal use only, wrong usage may destroy device
		virtual int			IsIdeTec(int deviceNo) ;			// return true if watchdog inverted
		virtual int			IsMonitoredSwitch(int deviceNo) ;	// return true if this is a monitored switch
		virtual int			SetTempOffset(int deviceNo, double Sollwert, double IstWert) ; // returns 1 if ok or 0 in case of an error
		virtual int			GetFrequency(int deviceNo, unsigned long int *counter, int subDevice) ;

#ifdef CC_USE_DEBUGWRITE
		virtual void		DebugWrite(CString &s) ;					// for internal use only
		virtual void		DebugWrite(_TCHAR *s) ;						// for internal use only
#endif	// CC_USE_DEBUGWRITE
	} ;

extern "C" {
	// for use of Class CUSBaccess from Delphi
	USBACCESS_API CUSBaccess * _stdcall USBaccessInitObject() ;
	USBACCESS_API void _stdcall USBaccessUnInitObject(CUSBaccess *) ;
	} ;
#else	// __cplusplus
typedef unsigned long int CUSBaccess ;
// typedef void * HANDLE ;	// defined in windows.h
enum FCWUSBactions {		LEDs=0, EEwrite=1, EEread=2, Reset=3, KeepCalm=4, GetInfo=5, StartMeasuring=6 } ;
enum FCWLED_IDs {			LED_0=0, LED_1=1, LED_2=2, LED_3=3 } ;
enum FCWSWITCH_IDs {		SWITCH_0=0x10, SWITCH_1=0x11, SWITCH_2=0x12, SWITCH_3=0x13 } ;
enum FCWUSBtype_enum {		ILLEGAL_DEVICE=0,
							LED_DEVICE=0x01,
							WATCHDOG_DEVICE=0x05,
							AUTORESET_DEVICE=0x06,
							SWITCH1_DEVICE=0x08,
							TEMPERATURE_DEVICE=0x10, 
							TEMPERATURE2_DEVICE=0x11,
							TEMPERATURE5_DEVICE=0x15, 
							HUMIDITY1_DEVICE=0x20,
							CONTACT00_DEVICE=0x30
							} ;

#endif	// __cplusplus

// functional C interface (FCW = Function CleWare)
#ifdef __cplusplus
 extern "C" {
#endif	// __cplusplus
	USBACCESS_API CUSBaccess * _stdcall	FCWInitObject(void) ;
	USBACCESS_API void _stdcall			FCWUnInitObject(CUSBaccess *obj) ;
	USBACCESS_API int _stdcall			FCWOpenCleware(CUSBaccess *obj) ;
	USBACCESS_API int _stdcall			FCWCloseCleware(CUSBaccess *obj) ;
	USBACCESS_API int _stdcall			FCWRecover(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API void * _stdcall		FCWGetHandle(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWGetValue(CUSBaccess *obj, int deviceNo, unsigned char *buf, int bufsize) ;
	USBACCESS_API int _stdcall			FCWSetValue(CUSBaccess *obj, int deviceNo, unsigned char *buf, int bufsize) ;
	USBACCESS_API int _stdcall			FCWSetLED(CUSBaccess *obj, int deviceNo, enum FCWLED_IDs Led, int value) ;	// value: 0=off 7=medium 15=highlight
	USBACCESS_API int _stdcall			FCWSetSwitch(CUSBaccess *obj, int deviceNo, enum FCWSWITCH_IDs Switch, int On) ;	//	On: 0=off, 1=on
	USBACCESS_API int _stdcall			FCWGetSwitch(CUSBaccess *obj, int deviceNo, enum FCWSWITCH_IDs Switch) ;			//	On: 0=off, 1=on, -1=error
	USBACCESS_API int _stdcall			FCWGetSeqSwitch(CUSBaccess *obj, int deviceNo, enum FCWSWITCH_IDs Switch, int seqNum) ;			//	On: 0=off, 1=on, -1=error
	USBACCESS_API int _stdcall			FCWGetSwitchConfig(CUSBaccess *obj, int deviceNo, int *switchCount, int *buttonAvailable) ;	
	USBACCESS_API int _stdcall			FCWGetTemperature(CUSBaccess *obj, int deviceNo, double *Temperature, int *timeID) ;
	USBACCESS_API float _stdcall		FCWDGetTemperature(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWGetHumidity(CUSBaccess *obj, int deviceNo, double *Humidity, int *timeID) ;
	USBACCESS_API float _stdcall		FCWDGetHumidity(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWSelectADC(CUSBaccess *obj, int deviceNo, int subDevice) ;
	USBACCESS_API float _stdcall		FCWGetADC(CUSBaccess *obj, int deviceNo, int sequenceNumber, int subDevice) ;
	USBACCESS_API int _stdcall			FCWResetDevice(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWStartDevice(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWCalmWatchdog(CUSBaccess *obj, int deviceNo, int minutes, int minutes2restart) ;
	USBACCESS_API int _stdcall			FCWGetVersion(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWGetUSBType(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWGetSerialNumber(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWGetDLLVersion(void) ;
	USBACCESS_API int _stdcall			FCWGetManualOnCount(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWGetManualOnTime(CUSBaccess *obj, int deviceNo) ;	
	USBACCESS_API int _stdcall			FCWGetOnlineOnCount(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWGetOnlineOnTime(CUSBaccess *obj, int deviceNo) ;	
	USBACCESS_API int _stdcall			FCWGetMultiSwitch(CUSBaccess *obj, int deviceNo, unsigned long int *mask, unsigned long int *value, int seqNumber) ;
	USBACCESS_API int _stdcall			FCWSetMultiSwitch(CUSBaccess *obj, int deviceNo, unsigned long int value) ;
	USBACCESS_API int _stdcall			FCWSetMultiConfig(CUSBaccess *obj, int deviceNo, unsigned long int directions) ;
	USBACCESS_API int _stdcall			FCWGetCounter(CUSBaccess *obj, int deviceNo, int counter) ;
	USBACCESS_API int _stdcall			FCWSyncDevice(CUSBaccess *obj, int deviceNo, unsigned long int mask) ;
	USBACCESS_API int _stdcall			FCWGetMultiConfig(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWIsAmpel(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWIsLuminus(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWIsAlarm(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWIsCutter(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWIsSolidState(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWIsWatchdogInvert(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWGetHWversion(CUSBaccess *obj, int deviceNo) ;
	USBACCESS_API int _stdcall			FCWIOX(CUSBaccess *obj, int deviceNo, int addr, int data) ;		// for internal use only, wrong usage may destroy device
	USBACCESS_API int _stdcall			FCWSetTempOffset(CUSBaccess *obj, int deviceNo, double Sollwert, double IstWert) ; // returns 1 if ok or 0 in case of an error
	USBACCESS_API int _stdcall			FCWGetFrequency(CUSBaccess *obj, int deviceNo, unsigned long int *counter, int subDevice) ; // returns frequency if ok or -1 in case of an error

#ifdef __cplusplus
	} ;
#endif	// __cplusplus
