import uuid
from csr.serializers.company_serializers import CompanyProfileWriteSerializer
cin = f"L12345MH2020PLC{uuid.uuid4().int % 900000 + 100000:06d}"
s = CompanyProfileWriteSerializer(data={
    'company_name': 'Apex Technologies India Ltd',
    'legal_name': 'Apex Technologies India Limited',
    'cin_number': cin,
    'pan_number': 'AAACT1234K',
    'contact_person_name': 'Test Lead',
    'contact_person_designation': 'Lead',
    'contact_email': 'test@co.com',
    'contact_phone': '+919876543210',
    'registered_address': 'Addr',
    'city': 'Mumbai',
    'state': 'Maharashtra',
    'pincode': '400001',
    'annual_csr_budget': '1000.00'
})
print('CIN:', cin, 'Valid?', s.is_valid())
if not s.is_valid():
    print('Errors:', s.errors)
