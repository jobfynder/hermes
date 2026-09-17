"""Conservative canonical-name validation; no model calls or broad stopword guesses."""
import re

# Standalone prose/metadata observed as incorrectly approved skills. Never
# apply these as substrings: e.g. 'Advanced SQL' is not the word 'Advanced'.
NON_SKILL_TERMS = frozenset({
    'receive','received','overall','collaborative','collaborate','supporting','supported',
    'ensure','ensures','enhance','enhanced','perform','performed','deliver','delivered',
    'recommendations','recommendation','participate','participating','understand','understanding',
    'required','preferred','qualification','qualifications','responsibilities','responsibility',
    'ability','abilities','excellent','strong','advanced','professional','certified',
    'employment type','job title','years of experience','skill','skills','requirements',
    'analysts','managers','defects','issues','material','materials','video','global',
    'include','includes','including','must','should','please','candidate','candidates',
    'resume','resumes','recruiter','recruiters','location','compensation','availability',
    'onsite','remote','hybrid','rate','salary','contact','email','phone','unsubscribe',
    'https','process','scalable','access','developer','architect','microsoft','program',
    'delivery','integrations','governance','dashboards','routing','status','site',
})

def skill_noise_reason(name: str) -> str | None:
    value=re.sub(r'\s+',' ',name or '').strip()
    if re.search(r'(?i)\b(?:stakeholders?|leadership|mentoring|teamwork|interpersonal|adaptability|adaptable|soft skills?|technical writing|time management|problem solv(?:ing|er)|contract negotiations)\b',value):
        return 'nontechnical_professional_skill'
    if re.search(r'(?i)\bcommunications?\b',value) and not re.search(r'(?i)\b(?:protocols?|network|wireless|serial|interprocess|inter-process|unified|devices?|systems?|TCP|MQTT|Modbus)\b',value):
        return 'nontechnical_professional_skill'
    if re.search(r'(?i)\b(?:collaborat(?:e|ing|ion)|presentations?)\b',value) and not re.search(r'(?i)\b(?:Miro|SharePoint|Teams|GitHub|Confluence|protocols?|tools?)\b',value):
        return 'nontechnical_professional_skill'
    if re.search(r'(?i)\banalytical skills\b|^exceptional analytical$|^writing and diagram',value):
        return 'nontechnical_professional_skill'
    if value.lower() in NON_SKILL_TERMS:
        return 'standalone_prose_or_metadata'
    words=re.findall(r"[A-Za-z0-9+#.]+",value)
    if len(words)>5 or len(value)>60:
        return 'prose_or_composite_term'
    if re.match(r'(?i)^(?:and|or|with|including|such as|prior knowledge of|experience with|familiarity with|ability to|expertise with|background in|certification such as)\s+',value):
        return 'sentence_fragment'
    if re.match(r'(?i)^(?:analyze|build|collaborate|configure|create|define|deliver|develop|document|drive|ensure|establish|implement|improve|lead|maintain|manage|monitor|oversee|perform|provide|review|support|troubleshoot|validate|write)\b',value):
        return 'responsibility_statement'
    if re.search(r'(?i)\b(?:is|required|preferred|years? of experience|client site|status updates?|latest .* updates?)\b',value):
        return 'requirement_or_prose'
    if re.search(r'(?i)(?:\s+or\s+|\b(?:and|or|etc)\.?$)',value):
        return 'incomplete_or_composite_term'
    if re.search(r'(?i)^(?:(?:senior|sr\.?|junior|jr\.?)\s+.*(?:engineer|architect|consultant|manager|team lead|developer)|(?:program|account|project|business development|delivery|bench sales) manager|data architect|architect)$',value):
        return 'job_title_not_skill'
    if re.match(r'(?i)^(?:and|or|including|prior knowledge of|experience with|familiarity with)\s+',value):
        return 'sentence_fragment'
    if value.count('(')!=value.count(')'):
        return 'truncated_parenthesis'
    if '@' in value or re.search(r'https?://|www\.',value,re.I):
        return 'contact_or_url'
    return None
