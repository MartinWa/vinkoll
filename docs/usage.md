# Usage

The interface is Swedish and works on phones and desktops. Every active account
shares the same catalogue and inventory. Wine details are entered manually, and
all cellar data is stored locally.

## Working with the application

1. **Viner → Lägg till vin** creates a wine profile. Enter its name, type, producer, origin, grapes, and bottle size. Saving a profile starts with zero bottles.
2. **Inställningar** creates or renames storage locations. Bottles without a location appear as **Utan plats**.
3. **Källare → Lägg till flaskor** adds bottles of an existing wine. Choose a location, quantity, actual vintage, and price paid per bottle. Leave an unknown price blank; zero is a valid price.
4. **Drick** consumes one bottle. When bottles differ by vintage, location, or price, select the group to consume from.
5. Open a wine in **Källare**, then use **Redigera flaska** to correct or move one bottle. **Historik** records additions, consumption, corrections, and moves.
6. **Viner** lets you edit, archive, restore, or delete profiles. Only unused profiles can be deleted. Archived wines with available bottles remain in Cellar; restore a profile before adding more bottles.
7. **Sök bland sparade viner** searches local records in Cellar or Wines, together with the current location/archive filter. Opening details and returning keeps that context.
8. Upload a photo in the wine editor. JPEG, PNG, WebP and HEIC/HEIF are supported, up to 20 MB and 40 megapixels. Photos are private, orientation is corrected, and display copies omit phone metadata. Choose the file again after an error or expired session; the remaining form input is preserved.
9. **Lägg till recension** saves a dated score and/or note separately. Scores use half-star steps from 1 to 5; blank is unrated. Earlier reviews remain in details and **Historik**, which filters by wine and action.
10. **Ta bort flaska** records a gift, loss or inventory adjustment. **Hantera plats** archives a location, moves its available bottles to another location or Unassigned, or restores it. Historical references are retained.

## Markdown snapshots

In **Inställningar → Skapa Markdown**, each section has its own Generate, raw-text preview and Copy action. **Alla viner, betyg och anteckningar** includes the full catalogue, archived/empty profiles, general notes and all reviews. **Aktuella flaskor** includes only available bottles within its own location scope, with grouped quantities and an explicit empty result. Both snapshots include the local timestamp/timezone and work without external services. If clipboard access is unavailable, select and copy the preview manually. Ordinary forms work without JavaScript; locally served HTMX keeps the two previews visible together when enabled.

## Saved input and retries

Inventory changes and their history are saved together. Retrying a bottle addition or consumption does not repeat the change, and concurrent bottle edits are detected before saving. Forms preserve unsaved input after a session expires.

If a session expires while saving, sign in again to recover the form. Browser drafts stay in the current tab and exclude passwords. If another edit has changed a bottle, use **Kasta osparade uppgifter och ladda om** to discard your draft and load the current details.

## Preferred store

The preferred Systembolaget store is currently entered as a name and ID; leading zeroes are preserved. Live store lookup and availability checks follow in a later stage, and product search/import after that.

## Sign-in

Username/password sign-in, password changes, and operator-managed accounts are supported. Every signed-in account can access all cellar records; grant accounts only to trusted household members.
