/**
 * MIL-STD-2525E SIDC (Symbol Identification Code) utilities
 * 
 * NOTE: These are fallback values. The source of truth is the backend /api/v1/config endpoint.
 * Functions accept optional config parameters to use values from appConfig when available.
 */

// Symbol Set 25 = Control Measures (Tactical Graphics)
// Affiliation modifiers for tactical graphics (position 3, 0-indexed)
// Fallback values - source of truth is backend
export const SIDC_AFFILIATION = {
  Friend: '3',      // Friendly
  Hostile: '6',     // Hostile/Faker
  Neutral: '4',     // Neutral
  Unknown: '1'      // Unknown
}

// Echelon codes for SIDC positions 9-10 (amplifier + amplifierDescriptor)
// These encode the echelon/size indicator
// Fallback values - source of truth is backend
export const SIDC_ECHELON = {
  Team: '11',
  Squad: '12',
  Section: '13',
  Platoon: '14',
  Company: '15',
  Battalion: '16',
  Regiment: '17',
  Brigade: '18',
  Division: '21',
  Corps: '22',
  Army: '23'
}

// Status codes for SIDC position 7 (MIL-STD-2525E)
// Fallback values - source of truth is backend
export const SIDC_STATUS = {
  Present: '0',
  Planned: '1',
  Anticipated: '2',
  Known: '3'
}

// Unit type codes for SIDC positions 11-16 (entity + entityType + entitySubType)
// Symbol Set 10 = Land Unit
// Format: entity(2) + entityType(2) + entitySubType(2)
// Fallback values - source of truth is backend
export const SIDC_UNIT_TYPE = {
  unit: '000000',           // Unspecified — plain frame, generic unit
  infantry: '121100',       // Movement and Maneuver > Infantry
  armor: '120500',          // Movement and Maneuver > Armor/Mechanized
  cavalry: '121300',        // Movement and Maneuver > Reconnaissance/Cavalry/Scout
  artillery: '130300',      // Fires > Field Artillery
  engineer: '140700',       // Protection > Engineer
  signal: '111000',         // Command and Control > Signal
  medical: '161300',        // Sustainment > Medical
  supply: '160200',         // Sustainment > All Classes of Supply
  maintenance: '161100',    // Sustainment > Maintenance
  transport: '163600',      // Sustainment > Transportation
  aviation: '120600',       // Movement and Maneuver > Army Aviation/Rotary Wing
  airdefense: '130100',     // Fires > Air Defense
  reconnaissance: '121300', // Movement and Maneuver > Reconnaissance/Cavalry/Scout
  specialforces: '121700',  // Movement and Maneuver > Special Forces
  headquarters: '110000',   // Command and Control
  military_police: '141200', // Protection > Military Police
}

// Keywords to detect affiliation from name
// Fallback values - source of truth is backend
export const AFFILIATION_KEYWORDS = {
  Friend: ['friendly', 'friend', 'allied', 'ally', 'blue', 'us ', 'usa', 'nato'],
  Hostile: ['hostile', 'enemy', 'red', 'opfor', 'opposing', 'adversary', 'threat'],
  Neutral: ['neutral', 'green', 'non-aligned', 'civilian'],
  Unknown: ['unknown', 'unidentified', 'pending', 'suspected'],
}

// Keywords to detect echelon from name
// Fallback values - source of truth is backend
export const ECHELON_KEYWORDS = {
  Team: ['team', 'fire team'],
  Squad: ['squad'],
  Section: ['section'],
  Platoon: ['platoon', 'plt'],
  Company: ['company', 'troop', 'battery', 'coy', 'co '],
  Battalion: ['battalion', 'btn', 'bn ', 'squadron'],
  Regiment: ['regiment', 'rgt', 'group'],
  Brigade: ['brigade', 'bde', 'bct'],
  Division: ['division', 'div'],
  Corps: ['corps'],
  Army: ['army', 'field army'],
}

/**
 * Generate SIDC for a military symbol based on affiliation, echelon, status, and unit type
 * Returns 20-character MIL-STD-2525E SIDC
 * 
 * Structure from mil-sym-ts Sidc class:
 * version(2) + context(1) + identity(1) + symbolSet(2) + status(1) + hqtfd(1) + 
 * amplifier(1) + amplifierDesc(1) + entity(2) + entityType(2) + entitySubType(2) + mod1(2) + mod2(2)
 * 
 * @param {string} affiliation - 'Friend', 'Hostile', 'Neutral', or 'Unknown'
 * @param {string} echelon - Echelon name (e.g., 'Battalion', 'Brigade')
 * @param {string} status - 'Present', 'Planned', 'Anticipated', or 'Known'
 * @param {string} unitType - Either a 6-digit entity code or a keyword like 'armor'
 * @param {Object} sidcConfig - Optional SIDC config from appConfig (defaults to fallback values)
 * @param {string} symbolSetCode - Optional symbol set code (defaults to '10' for Land Unit)
 * @returns {string} 20-character SIDC
 */
export const generateMilUnitSidc = (affiliation = 'Friend', echelon = 'Battalion', status = 'Present', unitType = 'unit', sidcConfig = null, symbolSetCode = '10') => {
  const affiliationMap = sidcConfig?.affiliation || SIDC_AFFILIATION
  const echelonMap = sidcConfig?.echelon || SIDC_ECHELON
  const statusMap = sidcConfig?.status || SIDC_STATUS
  const unitTypeMap = sidcConfig?.unitType || SIDC_UNIT_TYPE

  // Version 13 = MIL-STD-2525E (10 = 2525D); milsymbol 3.x renders both.
  const version = '13'
  const context = '0'
  const identity = affiliationMap[affiliation] || '3'
  // Use provided symbol set code, default to Land Unit (10)
  const symbolSet = symbolSetCode && symbolSetCode.length === 2 ? symbolSetCode : '10'
  const stat = statusMap[status] || '0'
  const hqtfd = '0'
  const echelonCode = echelonMap[echelon] || '00'  // 2 chars: amplifier + amplifierDesc (00 = no echelon)
  
  // unitType can be either:
  // 1. A 6-digit entity code directly (from symbol picker)
  // 2. A keyword like 'armor', 'infantry' (from name detection)
  let entityCode = '110300'  // Default generic unit
  if (unitType && unitType.length === 6 && /^\d+$/.test(unitType)) {
    // It's a direct 6-digit entity code
    entityCode = unitType
  } else if (unitType && unitTypeMap[unitType]) {
    // It's a keyword, look it up
    entityCode = unitTypeMap[unitType]
  }
  
  const mod1 = '00'
  const mod2 = '00'
  
  return `${version}${context}${identity}${symbolSet}${stat}${hqtfd}${echelonCode}${entityCode}${mod1}${mod2}`
}

/**
 * Update SIDC with a new affiliation code
 * @param {string} sidc - Original SIDC
 * @param {string} affiliation - New affiliation
 * @param {Object} sidcConfig - Optional SIDC config from appConfig (defaults to fallback values)
 * @returns {string} Updated SIDC
 */
export const updateSidcAffiliation = (sidc, affiliation, sidcConfig = null) => {
  if (!sidc || sidc.length < 4) return sidc
  const affiliationMap = sidcConfig?.affiliation || SIDC_AFFILIATION
  const affiliationCode = affiliationMap[affiliation] || '1'
  return sidc.substring(0, 3) + affiliationCode + sidc.substring(4)
}

/**
 * Detect affiliation from name using keywords
 * @param {string} name - Unit name
 * @param {Object} keywordsConfig - Optional keywords config from appConfig (defaults to fallback values)
 * @returns {string|null} Affiliation key or null if not detected
 */
export const detectAffiliationFromName = (name, keywordsConfig = null) => {
  if (!name) return null
  const nameLower = name.toLowerCase()
  const affiliationKeywords = keywordsConfig?.affiliation || AFFILIATION_KEYWORDS
  
  for (const [affiliation, keywords] of Object.entries(affiliationKeywords)) {
    for (const keyword of keywords) {
      if (nameLower.includes(keyword)) {
        return affiliation
      }
    }
  }
  return null
}

/**
 * Detect echelon from name using keywords
 * @param {string} name - Unit name
 * @param {Object} keywordsConfig - Optional keywords config from appConfig (defaults to fallback values)
 * @returns {string|null} Echelon key or null if not detected
 */
export const detectEchelonFromName = (name, keywordsConfig = null) => {
  if (!name) return null
  const nameLower = name.toLowerCase()
  const echelonKeywords = keywordsConfig?.echelon || ECHELON_KEYWORDS
  
  for (const [echelon, keywords] of Object.entries(echelonKeywords)) {
    for (const keyword of keywords) {
      if (nameLower.includes(keyword)) {
        return echelon
      }
    }
  }
  return null
}
