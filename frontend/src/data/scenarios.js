/**
 * ShopMate AI — Hardcoded Demo Scenarios
 *
 * This stands in for the real pipeline (Phase 2: Groq intent parsing,
 * Phase 3: LangGraph agent, Phase 4: real product APIs, Phase 5:
 * grounding/verifier). Every field here is shaped exactly like what
 * those phases will eventually produce for real, so swapping this
 * file out for live calls later won't require changing the UI.
 *
 * `sourceToolCallId` on each product mirrors the grounding mechanism
 * from the project doc — in the real system, every claim traces back
 * to a specific tool call. Here it's just a hardcoded label, but the
 * UI already treats it as real provenance data.
 *
 * 7 scenarios total, spanning categories with genuinely different
 * ranking attributes, to demonstrate category-adaptive ranking isn't
 * a two-category trick.
 */

const HEADPHONES_SCENARIO = {
  id: 'headphones',
  aisle: 'Electronics — Audio',
  matchKeywords: ['headphone', 'headphones', 'earphone', 'earbuds', 'anc', 'noise cancel'],
  parsedIntent: {
    category: 'Electronics — Headphones',
    budget: '₹8,000',
    mustHaves: ['Active Noise Cancellation', 'Wireless'],
  },
  trace: [
    { type: 'thought', text: 'User wants noise-cancelling headphones under ₹8,000. I need to search available products in the electronics category and filter by price and ANC support.' },
    { type: 'action', text: 'search_products(category="electronics", max_price=8000)', toolCallId: 'call_001' },
    { type: 'observation', text: 'Retrieved 6 candidate products from the product catalog.' },
    { type: 'thought', text: 'Headphones need to be ranked on ANC quality, battery life, and rating — not just price. Re-ranking by category-specific attributes.' },
    { type: 'action', text: 'rank_by_attributes(attributes=["anc", "battery_life", "rating"])', toolCallId: 'call_002' },
    { type: 'observation', text: 'Top 3 candidates identified. All claims below are grounded in call_001 and call_002 — nothing here was guessed.' },
  ],
  comparisonAttributes: ['Price', 'ANC', 'Battery Life', 'Rating'],
  products: [
    {
      id: 'demo-hp-1',
      title: 'SoundCore Aria ANC Wireless Headphones',
      price: 7499,
      rating: 4.4,
      ratingCount: 2140,
      icon: '🎧',
      attributes: { Price: '₹7,499', ANC: 'Yes (Hybrid)', 'Battery Life': '40 hrs', Rating: '4.4 / 5' },
      reasoning: 'Best ANC performance in budget, strongest battery life of the three, and highest review count — most reliable signal.',
      sourceToolCallId: 'call_002',
      isTopPick: true,
    },
    {
      id: 'demo-hp-2',
      title: 'PulseWave X2 Bluetooth Headphones',
      price: 6299,
      rating: 4.1,
      ratingCount: 890,
      icon: '🎧',
      attributes: { Price: '₹6,299', ANC: 'Yes (Basic)', 'Battery Life': '28 hrs', Rating: '4.1 / 5' },
      reasoning: 'Cheapest option with ANC, but noticeably shorter battery life and a smaller review sample.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
    {
      id: 'demo-hp-3',
      title: 'EchoFlow Studio Over-Ear',
      price: 7950,
      rating: 4.6,
      ratingCount: 430,
      icon: '🎧',
      attributes: { Price: '₹7,950', ANC: 'Yes (Adaptive)', 'Battery Life': '35 hrs', Rating: '4.6 / 5' },
      reasoning: 'Highest rating of the three, but close to budget ceiling and fewer reviews to back that rating.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
  ],
}

const SHOES_SCENARIO = {
  id: 'shoes',
  aisle: 'Footwear — Running',
  matchKeywords: ['shoe', 'shoes', 'sneaker', 'sneakers', 'running shoes', 'footwear'],
  parsedIntent: {
    category: 'Footwear — Running Shoes',
    budget: '₹5,000',
    mustHaves: ['Running', 'Breathable'],
  },
  trace: [
    { type: 'thought', text: 'User wants running shoes under ₹5,000. This category cares about cushioning, breathability, and fit — different attributes than electronics.' },
    { type: 'action', text: 'search_products(category="footwear", max_price=5000)', toolCallId: 'call_001' },
    { type: 'observation', text: 'Retrieved 5 candidate products from the product catalog.' },
    { type: 'thought', text: 'Re-ranking using footwear-specific attributes instead of the electronics ones used last time — this is the category-adaptive step.' },
    { type: 'action', text: 'rank_by_attributes(attributes=["cushioning", "breathability", "rating"])', toolCallId: 'call_002' },
    { type: 'observation', text: 'Top 3 candidates identified, grounded in call_001 and call_002.' },
  ],
  comparisonAttributes: ['Price', 'Cushioning', 'Breathability', 'Rating'],
  products: [
    {
      id: 'demo-sh-1',
      title: 'StrideMax Air Runner',
      price: 4499,
      rating: 4.5,
      ratingCount: 1620,
      icon: '👟',
      attributes: { Price: '₹4,499', Cushioning: 'High', Breathability: 'Excellent (mesh)', Rating: '4.5 / 5' },
      reasoning: 'Best all-around pick — high cushioning and excellent breathability, backed by the largest review sample.',
      sourceToolCallId: 'call_002',
      isTopPick: true,
    },
    {
      id: 'demo-sh-2',
      title: 'UrbanTrail Flex 2',
      price: 3299,
      rating: 4.0,
      ratingCount: 540,
      icon: '👟',
      attributes: { Price: '₹3,299', Cushioning: 'Medium', Breathability: 'Good', Rating: '4.0 / 5' },
      reasoning: 'Cheapest option, but cushioning and breathability are a step down from the top pick.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
    {
      id: 'demo-sh-3',
      title: 'VeloRun Pro Knit',
      price: 4899,
      rating: 4.3,
      ratingCount: 310,
      icon: '👟',
      attributes: { Price: '₹4,899', Cushioning: 'High', Breathability: 'Excellent (knit)', Rating: '4.3 / 5' },
      reasoning: 'Comparable comfort to the top pick, but closer to budget ceiling with fewer reviews.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
  ],
}

const LAPTOP_SCENARIO = {
  id: 'laptop',
  aisle: 'Electronics — Computing',
  matchKeywords: ['laptop', 'notebook', 'ultrabook', 'macbook'],
  parsedIntent: {
    category: 'Electronics — Laptops',
    budget: '₹60,000',
    mustHaves: ['16GB RAM', 'SSD Storage'],
  },
  trace: [
    { type: 'thought', text: 'User wants a laptop under ₹60,000 for general use. This category needs RAM, storage type, and processor generation to be weighed together — price alone is a poor proxy for value here.' },
    { type: 'action', text: 'search_products(category="computing", max_price=60000)', toolCallId: 'call_001' },
    { type: 'observation', text: 'Retrieved 7 candidate products from the product catalog.' },
    { type: 'thought', text: 'Re-ranking using compute-specific attributes: RAM, storage, battery life. None of the footwear/audio attributes apply here — this is the category-adaptive logic swapping its entire attribute set.' },
    { type: 'action', text: 'rank_by_attributes(attributes=["ram", "storage", "battery_life", "rating"])', toolCallId: 'call_002' },
    { type: 'observation', text: 'Top 3 candidates identified, grounded in call_001 and call_002.' },
  ],
  comparisonAttributes: ['Price', 'RAM', 'Storage', 'Battery Life', 'Rating'],
  products: [
    {
      id: 'demo-lp-1',
      title: 'CoreBook 14 Slim',
      price: 54999,
      rating: 4.3,
      ratingCount: 980,
      icon: '💻',
      attributes: { Price: '₹54,999', RAM: '16GB', Storage: '512GB SSD', 'Battery Life': '10 hrs', Rating: '4.3 / 5' },
      reasoning: 'Best balance of RAM, storage, and battery life within budget, with a solid review base.',
      sourceToolCallId: 'call_002',
      isTopPick: true,
    },
    {
      id: 'demo-lp-2',
      title: 'ZenPad Air 13',
      price: 48999,
      rating: 4.0,
      ratingCount: 610,
      icon: '💻',
      attributes: { Price: '₹48,999', RAM: '16GB', Storage: '256GB SSD', 'Battery Life': '12 hrs', Rating: '4.0 / 5' },
      reasoning: 'Cheaper and best battery life, but half the storage of the top pick.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
    {
      id: 'demo-lp-3',
      title: 'ForgeBook Pro 15',
      price: 59499,
      rating: 4.5,
      ratingCount: 350,
      icon: '💻',
      attributes: { Price: '₹59,499', RAM: '16GB', Storage: '512GB SSD', 'Battery Life': '8 hrs', Rating: '4.5 / 5' },
      reasoning: 'Highest rating and matching storage, but weakest battery life and closest to the budget ceiling.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
  ],
}

const BACKPACK_SCENARIO = {
  id: 'backpack',
  aisle: 'Bags & Travel',
  matchKeywords: ['backpack', 'bag', 'rucksack', 'travel bag'],
  parsedIntent: {
    category: 'Bags — Backpacks',
    budget: '₹3,000',
    mustHaves: ['Laptop Compartment', 'Water Resistant'],
  },
  trace: [
    { type: 'thought', text: 'User wants a laptop backpack under ₹3,000. Ranking attributes shift again here — capacity and water resistance matter, ANC/RAM do not.' },
    { type: 'action', text: 'search_products(category="bags", max_price=3000)', toolCallId: 'call_001' },
    { type: 'observation', text: 'Retrieved 5 candidate products from the product catalog.' },
    { type: 'thought', text: 'Re-ranking using bag-specific attributes: capacity, water resistance, and rating.' },
    { type: 'action', text: 'rank_by_attributes(attributes=["capacity", "water_resistance", "rating"])', toolCallId: 'call_002' },
    { type: 'observation', text: 'Top 3 candidates identified, grounded in call_001 and call_002.' },
  ],
  comparisonAttributes: ['Price', 'Capacity', 'Water Resistance', 'Rating'],
  products: [
    {
      id: 'demo-bp-1',
      title: 'TrailPack 28L Commuter',
      price: 2499,
      rating: 4.5,
      ratingCount: 1310,
      icon: '🎒',
      attributes: { Price: '₹2,499', Capacity: '28L', 'Water Resistance': 'High (coated)', Rating: '4.5 / 5' },
      reasoning: 'Largest capacity and best water resistance, with the strongest review base of the three.',
      sourceToolCallId: 'call_002',
      isTopPick: true,
    },
    {
      id: 'demo-bp-2',
      title: 'MetroCarry Slim 20L',
      price: 1799,
      rating: 4.1,
      ratingCount: 540,
      icon: '🎒',
      attributes: { Price: '₹1,799', Capacity: '20L', 'Water Resistance': 'Medium', Rating: '4.1 / 5' },
      reasoning: 'Cheapest and most compact, but noticeably less capacity and water resistance.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
    {
      id: 'demo-bp-3',
      title: 'UrbanShift 25L Anti-Theft',
      price: 2899,
      rating: 4.3,
      ratingCount: 275,
      icon: '🎒',
      attributes: { Price: '₹2,899', Capacity: '25L', 'Water Resistance': 'High (coated)', Rating: '4.3 / 5' },
      reasoning: 'Comparable water resistance to the top pick, but smaller capacity and closer to budget ceiling.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
  ],
}

const WATCH_SCENARIO = {
  id: 'watch',
  aisle: 'Wearables',
  matchKeywords: ['watch', 'smartwatch', 'fitness band', 'fitness tracker'],
  parsedIntent: {
    category: 'Wearables — Smartwatches',
    budget: '₹4,000',
    mustHaves: ['Heart Rate Monitor', 'Water Resistant'],
  },
  trace: [
    { type: 'thought', text: 'User wants a smartwatch under ₹4,000 with health tracking. This category weighs battery life and sensor accuracy over raw specs.' },
    { type: 'action', text: 'search_products(category="wearables", max_price=4000)', toolCallId: 'call_001' },
    { type: 'observation', text: 'Retrieved 6 candidate products from the product catalog.' },
    { type: 'thought', text: 'Re-ranking using wearable-specific attributes: battery life, sensor accuracy, display type.' },
    { type: 'action', text: 'rank_by_attributes(attributes=["battery_life", "sensors", "display", "rating"])', toolCallId: 'call_002' },
    { type: 'observation', text: 'Top 3 candidates identified, grounded in call_001 and call_002.' },
  ],
  comparisonAttributes: ['Price', 'Battery Life', 'Sensors', 'Display', 'Rating'],
  products: [
    {
      id: 'demo-wt-1',
      title: 'PulseFit Active 2',
      price: 3499,
      rating: 4.4,
      ratingCount: 2050,
      icon: '⌚',
      attributes: { Price: '₹3,499', 'Battery Life': '9 days', Sensors: 'HR + SpO2', Display: 'AMOLED', Rating: '4.4 / 5' },
      reasoning: 'Best sensor suite and display type in budget, with by far the largest review base.',
      sourceToolCallId: 'call_002',
      isTopPick: true,
    },
    {
      id: 'demo-wt-2',
      title: 'ChronoBand Lite',
      price: 2199,
      rating: 4.0,
      ratingCount: 780,
      icon: '⌚',
      attributes: { Price: '₹2,199', 'Battery Life': '14 days', Sensors: 'HR only', Display: 'LCD', Rating: '4.0 / 5' },
      reasoning: 'Longest battery life and cheapest, but a more basic sensor set and display.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
    {
      id: 'demo-wt-3',
      title: 'FitSquare Pro',
      price: 3899,
      rating: 4.5,
      ratingCount: 410,
      icon: '⌚',
      attributes: { Price: '₹3,899', 'Battery Life': '7 days', Sensors: 'HR + SpO2', Display: 'AMOLED', Rating: '4.5 / 5' },
      reasoning: 'Highest rating and matching sensors, but shortest battery life and closest to budget ceiling.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
  ],
}

const KITCHEN_SCENARIO = {
  id: 'kitchen',
  aisle: 'Home & Kitchen',
  matchKeywords: ['blender', 'mixer', 'kitchen', 'grinder', 'juicer'],
  parsedIntent: {
    category: 'Home & Kitchen — Blenders',
    budget: '₹3,500',
    mustHaves: ['700W+ Motor', 'Multiple Jars'],
  },
  trace: [
    { type: 'thought', text: 'User wants a blender/mixer-grinder under ₹3,500. Kitchen appliances rank on motor power, jar count, and warranty — a completely different attribute set again.' },
    { type: 'action', text: 'search_products(category="home-kitchen", max_price=3500)', toolCallId: 'call_001' },
    { type: 'observation', text: 'Retrieved 5 candidate products from the product catalog.' },
    { type: 'thought', text: 'Re-ranking using appliance-specific attributes: motor power, jar count, warranty period.' },
    { type: 'action', text: 'rank_by_attributes(attributes=["motor_power", "jar_count", "warranty", "rating"])', toolCallId: 'call_002' },
    { type: 'observation', text: 'Top 3 candidates identified, grounded in call_001 and call_002.' },
  ],
  comparisonAttributes: ['Price', 'Motor Power', 'Jars', 'Warranty', 'Rating'],
  products: [
    {
      id: 'demo-kt-1',
      title: 'HomeChef MaxGrind 750',
      price: 3199,
      rating: 4.3,
      ratingCount: 1540,
      icon: '🧃',
      attributes: { Price: '₹3,199', 'Motor Power': '750W', Jars: '3', Warranty: '2 years', Rating: '4.3 / 5' },
      reasoning: 'Strongest motor and longest warranty in budget, with the largest review base.',
      sourceToolCallId: 'call_002',
      isTopPick: true,
    },
    {
      id: 'demo-kt-2',
      title: 'QuickMix Essential',
      price: 2299,
      rating: 3.9,
      ratingCount: 620,
      icon: '🧃',
      attributes: { Price: '₹2,299', 'Motor Power': '500W', Jars: '2', Warranty: '1 year', Rating: '3.9 / 5' },
      reasoning: 'Cheapest, but weaker motor, fewer jars, and shorter warranty.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
    {
      id: 'demo-kt-3',
      title: 'PowerBlend Turbo',
      price: 3450,
      rating: 4.4,
      ratingCount: 290,
      icon: '🧃',
      attributes: { Price: '₹3,450', 'Motor Power': '800W', Jars: '3', Warranty: '2 years', Rating: '4.4 / 5' },
      reasoning: 'Strongest motor of all three and highest rating, but closest to budget ceiling with fewer reviews.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
  ],
}

const DEFAULT_SCENARIO = {
  id: 'default',
  aisle: 'General',
  matchKeywords: [],
  parsedIntent: {
    category: 'General',
    budget: 'Not specified',
    mustHaves: [],
  },
  trace: [
    { type: 'thought', text: 'Parsing the request into category, budget, and required attributes.' },
    { type: 'action', text: 'search_products(query="<user query>")', toolCallId: 'call_001' },
    { type: 'observation', text: 'Retrieved candidate products from the product catalog.' },
    { type: 'thought', text: 'Ranking candidates by price, rating, and relevance to the stated need.' },
    { type: 'action', text: 'rank_by_attributes(attributes=["price", "rating"])', toolCallId: 'call_002' },
    { type: 'observation', text: 'Top 3 candidates identified, grounded in call_001 and call_002.' },
  ],
  comparisonAttributes: ['Price', 'Rating'],
  products: [
    {
      id: 'demo-def-1',
      title: 'Everyday Essentials Pack A',
      price: 2499,
      rating: 4.2,
      ratingCount: 780,
      icon: '📦',
      attributes: { Price: '₹2,499', Rating: '4.2 / 5' },
      reasoning: 'Balanced choice on price and rating for this general query.',
      sourceToolCallId: 'call_002',
      isTopPick: true,
    },
    {
      id: 'demo-def-2',
      title: 'Everyday Essentials Pack B',
      price: 1999,
      rating: 3.9,
      ratingCount: 320,
      icon: '📦',
      attributes: { Price: '₹1,999', Rating: '3.9 / 5' },
      reasoning: 'Cheaper, but a noticeably lower rating.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
    {
      id: 'demo-def-3',
      title: 'Everyday Essentials Pack C',
      price: 2899,
      rating: 4.4,
      ratingCount: 210,
      icon: '📦',
      attributes: { Price: '₹2,899', Rating: '4.4 / 5' },
      reasoning: 'Highest rating, but fewer reviews and priciest of the three.',
      sourceToolCallId: 'call_002',
      isTopPick: false,
    },
  ],
}

export const SCENARIOS = [
  HEADPHONES_SCENARIO,
  SHOES_SCENARIO,
  LAPTOP_SCENARIO,
  BACKPACK_SCENARIO,
  WATCH_SCENARIO,
  KITCHEN_SCENARIO,
]

export const EXAMPLE_QUERIES = [
  { text: 'Noise-cancelling headphones under ₹8000', icon: '🎧' },
  { text: 'Running shoes under ₹5000', icon: '👟' },
  { text: 'A laptop under ₹60,000 with 16GB RAM', icon: '💻' },
  { text: 'Laptop backpack under ₹3000', icon: '🎒' },
  { text: 'Smartwatch under ₹4000 with heart rate monitor', icon: '⌚' },
  { text: 'Mixer grinder under ₹3500', icon: '🧃' },
]

export function pickScenario(query) {
  const lowerQuery = query.toLowerCase()
  const match = SCENARIOS.find((scenario) =>
    scenario.matchKeywords.some((keyword) => lowerQuery.includes(keyword))
  )
  return match || DEFAULT_SCENARIO
}
