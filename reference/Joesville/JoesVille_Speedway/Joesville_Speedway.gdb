Joesville_Speedway
{
  Filter Properties = rFRS TMOD NSCRS IndyCar
  Attrition = 30
  TrackName = Joesville Speedway
  EventName = Joesville Runabout
  VenueName = Joesville Speedway
  VenueIcon = Joesville\JoesvilleIcon.dds
  Location = Joesville, FL, USA
  Length = 0.656 KM / 0.41 Miles
  TrackType = Short Track Oval
  Track Record = Brad Shuber, 16.669
  FormationAndStart=2     // formation lap with rolling start (safety car leads the field and peels off into the pits)
  RollingStartLoc=1	  // Start from alternate grid
  TerrainDataFile=..\JoesVille_Speedway.tdf
  HeadlightsRequired = false  // whether headlights are required at night
  Max Vehicles = 45

  // DefaultScoring overrides
  FormationAndStart=2
  PitlaneBoundary = 1 // whether track has a defined pitlane, if 0 you must request a pitstop before your vehicle is serviced
  GarageDepth = 2.0   // distance before AI begin steering upon leaving garage
  RacePitKPH = 48.2802
  NormalPitKPH = 48.2802
  FormationSpeedKPH = 56.3269
  PitsClosedLaps = 2
  MinimumYellowLaps = 4
  LeadYellowLaps = 4
  TestDayStart = 13:00
  RaceLaps = 60
  RaceTime = 120

  NumStartingLights = 2 // Number of starting lights in sequence

  Latitude = 29.014          // degs from Equator (range: -90 to 90, positive is Northern Hemisphere)
  Longitude = -81.07         // degs from GMT (-180 to 180, positive is East)
  Altitude = 11.4           // meters above sea level
  RaceDate = March 21, 2012   // default date for the race
  TimezoneRelativeGMT = -5.0 // hours compared to Greenwich Mean Time (should be negative to the West)
//  DSTRange=(1, 1, 0, 9999)   // (start day 1.0-367, end day 1.0-367, start year, end year); multiple lines allowed
//  U.S. example, where DST changed in 2007 (previous and future changes not simulated here):
//  DSTRange=(94.8, 301.3, 1987, 2006) // approximation of 1st Sunday in April to last Sunday in October
//  DSTRange=(70.8, 308.3, 2007, 9999) // approximation of 2nd Sunday in March to first Sunday in November


///////////////////////////LOOSE OBJECT DATA///////////////////////////

Cone=(4.5, 0.4, 0.16, 0.4, 3000, 15, 0.64)
Post_Bin=(18.14, 1.96, 1.3, 1.96, 15000, 200, 0.7)

//<instance_name>=(<mass>, <inertia x>, <inertia y>, <inertia z>, <spring>, <damper>, <friction>)

///////////////////////////////////////////////////////////////////////

  // Cut track penalty threshold adjusters, to help tune, check score.cpp in a +trace=3 trace.txt file
  CutLeavingThresh = 2      // Threshold (in meters) for leaving track
  CutJoiningThresh = 0.95     // Threshold (in meters) for re-joining track
  CutPassPenalty = 0.7        // Penalty for each driver we pass (an inaccurate indicator)
  CutTimeRatioMax = 0.95      // Start penalizing even if we lose 5% of time
  CutTimeRatioPenalty = 0.375 // Penalty for fraction of time savings
  CutSecondsSaved = 0.675     // Penalty for each second saved
  CutWorstYawPenalty = 1.5    // Penalty for staying under control, the worst yaw angle gives us an indication of this and it follows the cosine of the angle of the car in relation to the road
  CutDirectionalPenalty = 1.0 // Penalty (actually reward) for being in wrong direction
  CutWarningThresh = 1.6      // Threshold for warning (or disallowance of lap), should be > CutWorstYawPenalty
  CutStopGoThresh = 3.0       // Threshold for immediate stop/go penalty

  SettingsFolder = Joesville Speedway
  SettingsCopy = Joesville.svm
  SettingsAI = Joesville.svm
}
