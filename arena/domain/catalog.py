PRODUCTS = [
    {"id": "coffee", "name": "冷萃咖啡", "unit": "瓶", "cost": 1000, "reference_price": 2200, "base_demand": 150, "base_supply": 190, "initial_stock": 35, "color": "#916548"},
    {"id": "oats", "name": "燕麦早餐", "unit": "份", "cost": 700, "reference_price": 1600, "base_demand": 115, "base_supply": 150, "initial_stock": 30, "color": "#c99b50"},
    {"id": "bar", "name": "能量棒", "unit": "支", "cost": 500, "reference_price": 1200, "base_demand": 170, "base_supply": 210, "initial_stock": 40, "color": "#668967"},
]

SCENARIOS = [
    {"id": "neighborhood", "name": "街区日常", "tag": "均衡市场", "description": "稳定客流，考验长期经营", "demand_multiplier": 1, "supply_multiplier": 1, "rent": 18000},
    {"id": "festival", "name": "周末市集", "tag": "高波动", "description": "节庆客流，捕捉增长机会", "demand_multiplier": 1.3, "supply_multiplier": 1.1, "rent": 23000},
    {"id": "supply-shock", "name": "供应链风暴", "tag": "资源竞争", "description": "供应收紧，现金与库存博弈", "demand_multiplier": 1.05, "supply_multiplier": 0.62, "rent": 16000},
]

STRATEGIES = [
    {
        "id": "balanced", "name": "稳健经营", "description": "平衡毛利与周转，保留现金缓冲", "approach": "balanced",
        "margin": 0.85, "stock_days": 1.3, "marketing_budget": 6500, "color": "violet",
        "prompt": "你是一位重视现金流的经营者。根据库存周转和实际需求控制采购，在合理毛利与销量之间取得平衡。保持足够现金支付后续经营成本。",
    },
    {
        "id": "discount", "name": "价格进攻", "description": "以价格竞争抢占份额，加快库存周转", "approach": "discount",
        "margin": 0.55, "stock_days": 1.7, "marketing_budget": 10500, "color": "orange",
        "prompt": "你是一位擅长价格竞争的经营者。观察公开的对手价格，用有利润的低价争取销量。补货保持积极，但不能盲目囤货或透支现金。",
    },
    {
        "id": "premium", "name": "品牌溢价", "description": "以品质定位争取高毛利和忠诚顾客", "approach": "premium",
        "margin": 1.35, "stock_days": 1.0, "marketing_budget": 16000, "color": "teal",
        "prompt": "你经营有品牌溢价的精品店。通过适度营销与合理的溢价保持毛利。观察消费者价格承受能力，避免高价造成库存积压。",
    },
    {
        "id": "adaptive", "name": "动态套利", "description": "随市场信号调整价格、采购与营销", "approach": "adaptive",
        "margin": 0.9, "stock_days": 1.4, "marketing_budget": 8500, "color": "blue",
        "prompt": "你是一位数据驱动的经营者。结合市场事件、历史销量、库存和对手价格调整策略。供应紧张时保护库存，滞销时及时降价回笼现金。",
    },
]

MERCHANT_NAMES = ["北辰商店", "橙子补给", "青禾市集", "蓝鲸便利"]
COLORS = ["violet", "orange", "teal", "blue"]
