import { API_URL } from "@/lib/env";

/* Photo de profil : contrôles avant l'envoi, réduction de l'image, adresse de la photo. */

export const PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;

/** Valeur de l'attribut `accept` du champ fichier. */
export const PHOTO_ACCEPT = PHOTO_TYPES.join(",");

export const PHOTO_MAX_OCTETS = 2 * 1024 * 1024;

/** Côté le plus long de l'image envoyée : suffisant pour un avatar, léger pour la connexion. */
export const PHOTO_TAILLE_PX = 512;

/** Message d'erreur si le fichier ne peut pas servir de photo, sinon undefined. */
export function validatePhoto(file: Pick<File, "type" | "size">): string | undefined {
  if (!(PHOTO_TYPES as readonly string[]).includes(file.type)) return "Choisissez une image JPEG, PNG ou WebP.";
  if (file.size > PHOTO_MAX_OCTETS) return "L'image ne doit pas dépasser 2 Mo.";
  if (file.size === 0) return "Ce fichier est vide.";
}

/**
 * Le backend renvoie un chemin (« /media/photos/7.jpg ») ou une URL complète :
 * un chemin est servi par le backend, on le préfixe donc par son adresse.
 * Seuls un chemin absolu ou une URL http(s) sont acceptés : toute autre valeur
 * (`javascript:`, `data:`, …) est ignorée pour éviter une injection dans `src`.
 */
export function resoudreUrlPhoto(url: string | null | undefined): string | null {
  if (!url) return null;
  if (url.startsWith("/")) return `${API_URL}${url}`;
  return /^https?:\/\//i.test(url) ? url : null;
}

/**
 * Réduit l'image à PHOTO_TAILLE_PX (côté le plus long) et la convertit en JPEG.
 * Une image déjà plus petite garde sa taille. Rejette la promesse si l'image est illisible.
 */
export async function reduirePhoto(file: Blob): Promise<Blob> {
  const image = await createImageBitmap(file);
  const echelle = Math.min(1, PHOTO_TAILLE_PX / Math.max(image.width, image.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(image.width * echelle);
  canvas.height = Math.round(image.height * echelle);

  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas indisponible");
  // Fond blanc : les zones transparentes d'un PNG ne deviennent pas noires en JPEG
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  image.close();

  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Conversion impossible"))), "image/jpeg", 0.85),
  );
}
