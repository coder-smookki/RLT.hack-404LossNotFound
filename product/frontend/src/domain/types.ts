export type Tone = 'success' | 'warning' | 'error' | 'info' | 'neutral' | 'accent';
export type JobStatus = 'awaiting_engine' | 'queued' | 'running' | 'complete' | 'partial' | 'empty' | 'failed';
export type Role = 'supplier' | 'manufacturer' | 'distributor' | 'unknown';
export type Origin = 'discovered' | 'history';
export type EvidenceKind = 'catalog' | 'history' | 'none';
export interface NeedItem { id: string; name: string; okpd2: string | null; quantity: string | null; }
export interface Procurement { lotId: string; subject: string; source: string; publishDate: string | null; price: string | null; customerInn: string | null; customerName: string | null; region: string; items: NeedItem[]; }
export interface Draft { id: string; mode: 'text' | 'codes' | 'csv'; text: string; codes: string[]; region: string; price: string; updatedAt: string; }
export interface LinkedSource { url?: string | null; excerpt?: string; published_at?: string | null; updated_at?: string | null; retrieved_at?: string | null; date_scope?: string; }
export interface SourceEvidence { id: string; companyId: string; title: string; url: string | null; excerpt: string; fetchedAt: string | null; available: boolean; identityVerified: boolean; isExample: boolean; publishedAt?: string | null; updatedAt?: string | null; verificationStatus?: string; verificationScope?: string; scope?: string; contentDate?: string | null; dateSemantics?: string | null; kind?: string | null; freshness?: { dated_activity_sources?: LinkedSource[] }; identity?: { evidence?: LinkedSource[] }; }
export interface ItemEvidence { itemId: string; kind: EvidenceKind; sourceId: string | null; reason: string; status?: 'match' | 'conflict' | 'unknown'; technicalStatus?: 'match' | 'conflict' | 'unknown'; }
export interface RoleAssertion { role: Role; verified: boolean; basis: string; scope: string; sourceId: string | null; }
export interface CompanyProfileField { value: unknown; status: 'verified' | 'unverified' | 'unknown' | 'conflict'; sourceIds: string[]; observedAt?: string | null; }
export interface HistoryStats { lotCount: number; winnerLotCount: number; period: string; source: string; scope: string; }
export interface CompanyProfile { inn: string; version: string; contentHash: string; updatedAt: string | null; fields: Record<string, CompanyProfileField>; sources: SourceEvidence[]; completeness: { verifiedFields: number; totalFields: number; missingFields: string[] }; historyStats?: HistoryStats | null; }
export interface CompanyHistory { inn: string; lotCount: number; firstSeen: string | null; lastSeen: string | null; sourceCounts: Record<string, number>; topCategories: { code: string; lotCount: number }[]; subjects: { text: string; lotCount: number }[]; examples: { lotId: string; date: string | null; subject: string; source: string; observedStatus: 'participant' }[]; scope: string; }
export interface DueDiligence { summary: string; checks: { id: string; title: string; status: 'verified' | 'unverified' | 'observed' | 'unknown' | 'conflict'; value: unknown; sourceIds: string[]; limitation: string }[]; }
export interface SourceRefreshJob { id: string; inn: string; status: 'queued' | 'running' | 'complete' | 'needs_source' | 'unconfirmed' | 'failed'; message: string; checkedAt: string | null; nextAllowedAt: string | null; checkKind?: 'catalog_lookup' | 'official_site'; }
export interface SourceRefreshResponse { jobs: SourceRefreshJob[]; message?: string; }
export interface Company { currentProfile?: CompanyProfile | null; profileAtCalculation?: CompanyProfile | null; historySummary?: CompanyHistory | null; dueDiligence?: DueDiligence; sourceRefresh?: SourceRefreshJob | null; id: string; name: string; inn: string | null; kpp: string | null; region: string | null; website: string | null; origin: Origin; role: RoleAssertion; sources: SourceEvidence[]; history: HistoryRecord[]; newToFullHistory?: boolean | null; newToFrozenHistory?: boolean | null; displayName?: string | null; }
export interface HistoryRecord { id: string; lotId: string; date: string; subject: string; observedStatus: string; url: string | null; }
export interface ExplanationCriterion { code: string; label: string; basis: string; sourceIds: string[]; status: 'support' | 'conflict' | 'unknown'; }
export interface Recommendation { explanationSummary?: string; explanationCriteria?: ExplanationCriterion[]; explanationNotes?: string[]; company: Company; rank: number; reason: string; evidence: ItemEvidence[]; score?: number | null; scoreKind?: 'historical_rank' | 'external_retrieval'; rawEvidence?: Record<string, unknown>; }
export interface QueryJob { id: string; status: string; attempts: number; createdAt: string; startedAt: string | null; finishedAt: string | null; message: string; errorCode: string | null; }
export interface QueryRecord { id: string; draftId: string | null; importId?: string | null; procurement: Procurement; status: JobStatus; createdAt: string; resultVersion: string; recommendations: Recommendation[]; externalCandidates?: Recommendation[]; warnings: string[]; saved: boolean; exported: boolean; message?: string; job?: QueryJob | null; processedAt?: string | null; modelVersion?: string | null; catalogVersion?: string | null; }
export interface Issue { severity: 'error' | 'warning' | 'info'; code: string; file: string; row: number; field: string; message: string; action: string; lotId?: string; }
export interface ImportResult { id: string; files: string[]; procurements: Procurement[]; issues: Issue[]; rows: { notices: number; items: number }; queryIds: string[]; }
export interface SourceJob { id: string; status: JobStatus; message: string; updatedAt: string | null; published: boolean; }
export interface ExportRequest { queryId: string; companyIds: string[]; resultVersion: string; format: 'csv' | 'json' | 'pdf'; }
export interface ExportPayload { query: QueryRecord; recommendations: Recommendation[]; generatedAt: string; format: 'csv' | 'pdf'; filename: string; }
export interface ExportRecord { id: string; queryId: string; format: 'csv' | 'pdf'; createdAt: string; companyIds: string[]; }
export interface Analytics { period: string; notices: number; items: number; inn: number; codes: number; withSuppliers: number; withoutSuppliers: number; categories: { code: string; rows: number }[]; sources: { name: string; lots: number }[]; years: { year: string; lots: number }[]; sourceNote: string; }
export interface ApiErrorBody { error: { code: string; message: string; fields?: Record<string, string> }; }
export const TEAM_NAME = '404: Loss not found';
export const ROLE_LABEL: Record<Role, string> = { supplier: 'Поставщик', manufacturer: 'Производитель', distributor: 'Дистрибьютор', unknown: 'Не определена' };
export const STATUS_LABEL: Record<JobStatus, string> = { awaiting_engine: 'Не запущен', queued: 'В очереди', running: 'Идёт подбор', complete: 'Готово', partial: 'Частично', empty: 'Нет кандидатов', failed: 'Не завершён' };
export const STATUS_TONE: Record<JobStatus, Tone> = { awaiting_engine: 'neutral', queued: 'neutral', running: 'info', complete: 'success', partial: 'warning', empty: 'neutral', failed: 'error' };
export const READY_STATUSES: readonly JobStatus[] = ['complete', 'partial', 'empty'];
export const EVIDENCE_LABEL: Record<EvidenceKind, string> = { catalog: 'Сведения в каталоге', history: 'Похожая позиция в истории', none: 'Сведений не найдено' };
