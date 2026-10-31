# Tesla showroom refinement

Recommended discovery balances mileage, photo coverage, model year, and asking-price comparisons. It interleaves models. Price and distance sorts retain their explicit ordering.

Pricing uses up to 21 nearest-mileage peers within the same model, year, listed trim, inferred/listed drivetrain, and mileage band. The target VIN is excluded. At least five peers are required. Extreme asking prices are removed. Mileage adjustments are bounded and cannot reward additional mileage. References round to $100 to avoid false precision. Proposals retain the dealer-net floor and configurable buyer buffer. No spread ceiling or optimality claim is introduced. Asking prices do not prove sale prices or profits.

Cards show one compact estimate label and a shared tax/title/delivery disclosure. Repeated $500 discount labels are replaced with an explicit mileage-adjusted comparison description. Unknown zero odometer values are not promoted as low-mileage facts.

Drivetrain labels distinguish listed specifications from VIN-derived inferences. Model/year-specific motor tables come from Tesla service documentation:

- https://service.tesla.com/docs/Model3/ServiceManual/en-au/air/GUID-0C797294-574D-4EE4-8017-C339A7D58411.html
- https://service.tesla.com/docs/Model3/ServiceManual/2024/en-us/GUID-B7B9507C-C984-41F2-89EE-D23CA4E682ED.html
- https://service.tesla.com/docs/ModelY/ServiceManual/en-us/GUID-0C797294-574D-4EE4-8017-C339A7D58411.html
- https://service.tesla.com/docs/ModelY/ServiceManual/2025/en-au/air/GUID-BB4CE449-3F8E-4905-AF4A-96DFA87535B5.html
- https://service.tesla.com/docs/Cybertruck/ServiceManual/en-us/GUID-54943431-2184-4BBC-9E1E-B02363DEF429.html

Factory labels are VIN-derived. Neither drivetrain nor factory inference proves actual vehicle condition or present equipment. Unsupported drive codes remain unknown. Raw trim names remain advertised specifications.

HW3/HW4 filters require an explicit hardware generation, hardware_verified=true, and hardware_evidence_reference. There are currently zero evidenced hardware listings. These filter choices remain disabled. FSD software is a separate verification item. See https://www.tesla.com/support/ai-computer.

Under $25k is a budget filter. The federal previously owned clean vehicle credit is unavailable for vehicles acquired after September 30, 2025. No credit eligibility or savings claim is made. Source: https://www.irs.gov/clean-vehicle-tax-credits.

ZIP selection uses bundled GeoNames postal centers and inferred city centers. The public data files contain no customer information. The ZIP stays in browser storage; no third-party ZIP lookup is called. Approximate straight-line distances are neither driving distances nor shipping quotes. Unknown ZIPs show an error instead of inventing a location. The downloaded postal dataset is dated 2015-06-15 and may omit newer ZIPs. GeoNames provides the data without accuracy or completeness guarantees. The footer credits GeoNames under CC BY 3.0: https://www.geonames.org/export/zip/.

The VDP shows useful facts first, with title, inspection, equipment, FSD, and availability checks in an expandable section. Quote and payment gates remain enforced by the backend. Public reservations remain unconnected as agreed.

The neutral visual theme uses system typography, eager first-six images, visible images before load-handler completion, and compact vehicle details. Static and backend browser suites verify the new controls and the existing purchase lifecycle separately.

## Pricing update

The later platform-checkout release removes the mandatory $500 buyer buffer. See BUSINESS_OPERATING_MODEL.md for the current policy.
