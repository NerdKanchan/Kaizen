const SUPPORTED = /\.(pdf|xlsx|xlsm|csv)$/i;
export const MAX_RUN_BYTES = 250 * 1024 * 1024;

export function supportedRunFiles(files: File[]): File[] {
  return files.filter(file => SUPPORTED.test(file.name) && !file.name.startsWith(".") && !file.name.startsWith("~$"));
}

export function uploadProblem(files: File[]): string | null {
  if (!files.length) return "Choose PDF, XLSX, XLSM or CSV documents to check.";
  if (files.reduce((total, file) => total + file.size, 0) > MAX_RUN_BYTES) return "Upload at most 250 MB per run. Choose a smaller folder or fewer documents.";
  return null;
}
