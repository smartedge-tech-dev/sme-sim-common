// Company (vendor) presets and texts. Texts from sme-bac-sim v0.4.0 (d8382883dd7a6f2942659e7e230eef5f153274ca):
// static/app.js PRODUCT.vendor + en "vendor.*", static/i18n/{ja,zh}.js "vendor.*" (from smartedge-tech.com),
// plus the former shell.vendor.* / shell.help.custom strings of shell.js (renamed to vendor.*).
"use strict";
Shell.vendors = Shell.vendors || {};
Shell.vendors.smartEdge = {
  name: "smart-edge",
  nameLocal: "智届科技",
  url: "https://smartedge-tech.com",
  contactUrl: "https://smartedge-tech.com/contact/",
  email: "business@smartedge-tech.com",
  logoUrl: "/sme-sim-common/brand/company-logo.svg",
  blurb: "vendor.blurb",
  services: ["vendor.svc.ems", "vendor.svc.market", "vendor.svc.edge", "vendor.svc.integration",
    "vendor.svc.ai", "vendor.svc.cloud"],
};

Shell.addStrings("en", {
  "vendor.blurb": "Nanjing Smart-Edge Technology Co., Ltd. (南京智届科技有限公司) has, since its founding in 2023, " +
    "developed end-to-end software for distributed energy resources such as solar, batteries and EVs — " +
    "from equipment control to the cloud and electricity markets. The team supports projects in Japanese, " +
    "from requirements definition through design, implementation, operation and maintenance.",
  "vendor.svc.ems": "Energy management systems (EMS)",
  "vendor.svc.market": "RA / AC systems for electricity markets (JEPX, EPRX, OCCTO)",
  "vendor.svc.edge": "Edge IoT and equipment-control software",
  "vendor.svc.integration": "Equipment integration: Modbus, MQTT, BACnet, ECHONET Lite, OpenADR 2.0b",
  "vendor.svc.ai": "Energy forecasting and data analytics",
  "vendor.svc.cloud": "Cloud infrastructure design, build and operation",
  "vendor.help.custom": "Custom development…",
  "vendor.developedBy": "Developed by",
  "vendor.customDev": "Custom development",
  "vendor.contactUs": "Contact us",
  "vendor.available": "Custom development available",
  "vendor.website": "Website",
  "vendor.contactPage": "Contact page",
  "vendor.logo": "{name} logo",
});

Shell.addStrings("ja", {
  "vendor.blurb": "南京智届科技有限公司は、2023年の設立以来、太陽光・蓄電池・EV などの分散型エネルギー資源を対象に、" +
    "設備制御からクラウド、電力市場まで一貫したソフトウェアを開発しています。" +
    "要件定義から設計、実装、運用保守まで日本語で対応します。",
  "vendor.svc.ems": "エネルギーマネジメントシステム（EMS）の開発・提供",
  "vendor.svc.market": "電力市場向け RA・AC システムの開発・提供（JEPX・EPRX・OCCTO）",
  "vendor.svc.edge": "エッジ IoT・設備制御ソフトウェア",
  "vendor.svc.integration": "Modbus・MQTT・BACnet・ECHONET Lite・OpenADR 2.0b 等の設備接続",
  "vendor.svc.ai": "エネルギー予測・データ分析",
  "vendor.svc.cloud": "クラウドインフラの設計・構築・運用",
  "vendor.help.custom": "カスタム開発のご相談…",
  "vendor.developedBy": "開発元",
  "vendor.customDev": "カスタム開発",
  "vendor.contactUs": "お問い合わせ",
  "vendor.available": "カスタム開発を承ります",
  "vendor.website": "Web サイト",
  "vendor.contactPage": "お問い合わせページ",
  "vendor.logo": "{name} ロゴ",
});

Shell.addStrings("zh", {
  "vendor.blurb": "南京智届科技有限公司自 2023 年成立以来，围绕光伏、储能与 EV 等分布式能源资源，" +
    "开发覆盖设备控制、云端和电力市场的软件。从需求定义、设计、实现到运维，均可使用日语沟通。",
  "vendor.svc.ems": "能源管理系统（EMS）开发与提供",
  "vendor.svc.market": "电力市场 RA・AC 系统开发与提供（JEPX、EPRX、OCCTO）",
  "vendor.svc.edge": "边缘 IoT 与设备控制软件",
  "vendor.svc.integration": "接入 Modbus、MQTT、BACnet、ECHONET Lite、OpenADR 2.0b 等协议",
  "vendor.svc.ai": "能源预测与数据分析",
  "vendor.svc.cloud": "云基础设施设计、建设与运营",
  "vendor.help.custom": "定制开发咨询…",
  "vendor.developedBy": "开发方",
  "vendor.customDev": "定制开发",
  "vendor.contactUs": "联系我们",
  "vendor.available": "可承接定制开发",
  "vendor.website": "官网",
  "vendor.contactPage": "联系页面",
  "vendor.logo": "{name} 标志",
});
